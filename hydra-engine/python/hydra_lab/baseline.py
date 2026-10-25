"""Bounded, fail-closed baseline collector. Never starts or stops a backend."""
import argparse
import csv
import hashlib
import http.client
import ipaddress
import json
import math
from pathlib import Path
import statistics
import time
import tomllib
from urllib.parse import urlsplit


def require_idle(app_root):
    path = Path(app_root) / 'data/.gpu-campaign.lock'
    if path.exists():
        raise RuntimeError('GPU reserved; no inference submitted. Release through the owning app, never delete its lock.')


def validate_url(url):
    parsed = urlsplit(url)
    try:
        local = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        local = False
    if (parsed.scheme != 'http' or not local or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('Use a literal loopback HTTP origin without path, credentials, query or fragment')
    return parsed


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values)*p)-1)] if values else None


def consume_sse(stream, start, clock=time.perf_counter):
    content, arrivals, done, usage = [], [], False, None
    event_bytes = 0
    for line in stream:
        event_bytes += len(line)
        if event_bytes > 8*1024*1024:
            raise ValueError('SSE response exceeds 8 MiB limit')
        if not line.startswith(b'data:'):
            continue
        raw = line[5:].strip()
        if raw == b'[DONE]':
            done = True
            break
        data = json.loads(raw)
        now = clock()
        if data.get('error'):
            raise ValueError('Backend stream error')
        if data.get('usage'):
            usage = data['usage']
        choices = data.get('choices', [])
        delta = choices[0].get('delta', {}) if choices else {}
        # Include reasoning in arrival timing, but retain text separately.
        text = delta.get('content') or ''
        if text or delta.get('reasoning_content') or delta.get('reasoning'):
            arrivals.append(now)
        if text:
            content.append(text)
    wall = clock()-start
    if not done or not arrivals:
        raise ValueError('Incomplete SSE stream or no generated content')
    tokens = usage.get('completion_tokens') if usage else None
    if type(tokens) is not int or tokens <= 0:
        tokens = None
    gaps = [b-a for a, b in zip(arrivals, arrivals[1:])]
    return dict(wall_s=wall, ttft_s=arrivals[0]-start, output_tokens=tokens,
                output_tok_s=tokens/wall if tokens else None,
                inter_chunk_p50_s=percentile(gaps, .5),
                inter_chunk_p95_s=percentile(gaps, .95),
                inter_token_latency_s=None,
                timing_note='SSE chunks may contain multiple tokens; wall rate includes prefill.',
                content=''.join(content))


def request(url, payload, timeout):
    parsed = validate_url(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=timeout)
    started = time.perf_counter()
    try:
        connection.request('POST', '/v1/chat/completions', body=payload,
                           headers={'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'Backend HTTP {response.status}')
        if 'text/event-stream' not in response.getheader('Content-Type', ''):
            raise ValueError('Backend did not return SSE')
        result = consume_sse(response, started)
        text = result.pop('content')
        result['response_sha256'] = hashlib.sha256(text.encode()).hexdigest()
        result['nonempty_text'] = bool(text.strip())
        return result
    finally:
        connection.close()


def compare(rows):
    measured = [r for r in rows if not r['warmup']]
    pairs = {}
    for row in measured:
        group = pairs.setdefault(row['pair'], {})
        if row['arm'] in group:
            raise ValueError('Duplicate arm')
        group[row['arm']] = row
    changes = []
    for group in pairs.values():
        if set(group) != {'native', 'hydra'}:
            raise ValueError('Unpaired measurement')
        a, b = group['native'], group['hydra']
        if (a['request_sha256'] != b['request_sha256'] or
                not a.get('output_tokens') or a['output_tokens'] != b.get('output_tokens')):
            raise ValueError('Payloads or generated token counts not equivalent')
        changes.append(100*(b['wall_s']/a['wall_s']-1))
    if not changes:
        raise ValueError('No paired measurements')
    median = statistics.median(changes)
    return dict(paired_wall_regression_percent=changes, median_wall_regression_percent=median,
                passes_5_percent=median <= 5, scope='wall latency only; not complete performance gate',
                promotion=False)


def performance_gate(rows, limit_percent=5.):
    # Validate equivalence first; metric availability alone cannot establish it.
    compare(rows)
    arms={arm:[r for r in rows if r['arm']==arm and not r['warmup']]
          for arm in ('native','hydra')}
    metrics={}
    missing=[]
    for key,higher_is_better in [('wall_s',False),('ttft_s',False),('decode_tok_s',True)]:
        values={arm:[r.get(key) for r in group] for arm,group in arms.items()}
        if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for group in values.values() for v in group):
            missing.append(key)
            continue
        for label,p in [('p50',.5),('p05' if higher_is_better else 'p95',.05 if higher_is_better else .95)]:
            a,b=(percentile(values[arm],p) for arm in ('native','hydra'))
            regression=100*((a/b if higher_is_better else b/a)-1)
            metrics[f'{key}.{label}']=dict(native=a,hydra=b,regression_percent=regression,passes=regression<=limit_percent)
    count=min(len(v) for v in arms.values())
    complete=not missing and count>=5
    failed=[name for name,row in metrics.items() if not row['passes']]
    return dict(complete=complete,passes=not failed if complete else None,
                failed_metrics=failed,missing_metrics=missing,measured_pairs=count,metrics=metrics,
                scope='preliminary latency/decode gate only; not semantic, memory, energy or statistical proof',promotion=False)


def save(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    rows = report.get('rows', [])
    if rows:
        with path.with_suffix('.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
            writer.writeheader()
            writer.writerows({key:json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value
                              for key,value in row.items()} for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text(encoding='utf-8'))
    report = dict(schema=1, status='running', rows=[], config=config,
                  started_at=time.time(), cold_start='not measured: externally managed backend',
                  device_metrics='collect separately; not inferred from endpoint', promotion=False)
    try:
        if config.get('schema') != 1:
            raise ValueError('Unsupported config schema')
        require_idle(config['app_root'])
        endpoints = [('native', config['native_url'])]
        if config.get('hydra_url'):
            endpoints.append(('hydra', config['hydra_url']))
        for _, url in endpoints:
            validate_url(url)
        warmup, runs = config['warmup'], config['runs']
        if type(warmup) is not int or type(runs) is not int or warmup < 1 or runs < 3:
            raise ValueError('Require >=1 warmup and >=3 measured repetitions')
        payload = config['request']
        if not payload.get('model') or not payload.get('messages') or payload.get('stream') is not True:
            raise ValueError('Explicit model, messages and stream=true required')
        if type(payload.get('max_tokens')) is not int or not 1 <= payload['max_tokens'] <= 4096:
            raise ValueError('max_tokens must be 1..4096')
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        for i in range(warmup+runs):
            order = endpoints if i % 2 == 0 else list(reversed(endpoints))
            for arm, url in order:
                require_idle(config['app_root'])
                row = request(url, raw, config.get('timeout_s', 120))
                row.update(arm=arm, pair=i, warmup=i < warmup, request_sha256=digest)
                report['rows'].append(row)
                save(args.output, report)
        report['summary'] = {}
        for arm, _ in endpoints:
            rows = [r for r in report['rows'] if r['arm'] == arm and not r['warmup']]
            report['summary'][arm] = {key:dict(p50=percentile([r[key] for r in rows if r[key] is not None], .5),
                                                      p95=percentile([r[key] for r in rows if r[key] is not None], .95))
                                      for key in ('wall_s', 'ttft_s', 'output_tok_s')}
        if len(endpoints) == 2:
            report['comparison'] = compare(report['rows'])
        report['status'] = 'complete'
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        report.update(status='blocked' if isinstance(error, RuntimeError) else 'failed', error=str(error))
    finally:
        save(args.output, report)
    print(json.dumps({k:v for k,v in report.items() if k in ('status','error','summary')}, indent=2))
    return 0 if report['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
