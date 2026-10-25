"""Validate paired resident-memory reports and summarize measured requests."""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def summarize(stamp):
    names = ('ram16-auto-a1', 'full-resident-b1', 'full-resident-b2', 'ram16-auto-a2')
    reports = [json.loads((ROOT / 'data/benchmarks' / f'{stamp}-iq3-memory-{name}.json').read_text()) for name in names]
    rows = []
    for report in reports:
        assert report['status'] == 'complete', 'Incomplete benchmark'
        assert report['protocol'] == reports[0]['protocol'], 'Different protocol'
        assert report['binary_sha256'] == reports[0]['binary_sha256'], 'Different executable'
        assert len(report['rows']) == 10, 'Missing requests'
        measured = [r for r in report['rows'] if not r['warmup']]
        assert len(measured) == 5, 'Missing measured requests'
        assert all(r['output_tokens'] == 256 and r['reused'] == 0 for r in report['rows']), 'Output length or prompt reuse differs'
        rows.append(measured)
    assert all([r['prompt_sha256'] for r in group] == [r['prompt_sha256'] for r in rows[0]] for group in rows), 'Unpaired prompts'
    metrics = ('decode_tok_s', 'prefill_tok_s', 'wall_tok_s', 'wall_s')
    medians = [{key: statistics.median(r[key] for r in group) for key in metrics} for group in rows]
    pooled = {}
    for key in metrics:
        control = statistics.median(r[key] for i in (0, 3) for r in rows[i])
        candidate = statistics.median(r[key] for i in (1, 2) for r in rows[i])
        pooled[key] = {'ram16': control, 'full_resident': candidate, 'change_percent': (candidate / control - 1) * 100}
    result = {'status': 'complete', 'stamp': stamp, 'binary_sha256': reports[0]['binary_sha256'], 'protocol': reports[0]['protocol'], 'arm_medians': dict(zip(names, medians)), 'pooled': pooled, 'measured_requests': 20, 'warmup_requests': 20, 'limitations': ['One ABBA cycle; no statistical significance claim', 'Functional quality and endurance require separate checks', 'Decode differs from end-to-end throughput']}
    path = ROOT / 'output/verification' / f'{stamp}-full-resident-abba-summary.json'
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    summarize(sys.argv[1])
