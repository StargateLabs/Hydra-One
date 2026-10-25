"""Reproducible serial inference benchmark. Does not mutate config or restart services.

Use an idle dedicated server; keep the same model, binary and prompts between arms.
python tools/benchmark_local.py --config strata-iq3_xxs.json --label baseline
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.configuration import atomic_json
from serve.diagnostics import config_fingerprint

TIMING = re.compile(r"prompt (\d+) tokens = (\d+) reused \+ (\d+) read in ([\d.]+) ms "
                    r"\(([\d.]+) tok/s\), (\d+) generated in ([\d.]+) ms \(([\d.]+) tok/s\)")
FIELDS = ("prompt_tokens", "reused", "read_tokens", "prefill_ms", "prefill_tok_s", "generated", "decode_ms", "decode_tok_s")
PARAGRAPH = "La cache degli esperti conserva i pesi più usati in VRAM. Gli esperti non residenti richiedono lavoro sulla CPU o trasferimenti. Descrivi il percorso dei dati e i compromessi fra latenza, memoria e qualità. "


def summarize(rows):
    measured = [r for r in rows if not r["warmup"]]
    out = {}
    for key in ("decode_tok_s", "prefill_tok_s", "wall_tok_s", "wall_s"):
        values = [r[key] for r in measured]
        out[key] = {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)} if values else None
    return out


def new_timings(path, offset, identity):
    with path.open("rb") as f:
        st = os.fstat(f.fileno())
        if (st.st_dev, st.st_ino) != identity or st.st_size < offset:
            raise RuntimeError("Engine log restarted during a request; arm invalid")
        f.seek(offset)
        return TIMING.findall(f.read().decode("utf-8", "replace"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--url", default="http://127.0.0.1:8088")
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--runs", type=int, default=5)
    p.add_argument("--tokens", type=int, default=300)
    p.add_argument("--paragraphs", type=int, default=24)
    p.add_argument("--prompt-set", default="iq3-paired-v1", help="Same value gives identical prompts across isolated arms")
    p.add_argument("--output", type=Path, default=Path("data/benchmarks/latest.json"))
    p.add_argument("--prompt-file",type=Path,help="Local custom prompt; nonce remains paired across configurations")
    p.add_argument('--stop-file',type=Path,help='Stop between requests when this file appears')
    p.add_argument('--interleave-minp',action='store_true',help='Paired 0.5/0.7 requests in one instance; prompt caching must be disabled')
    a = p.parse_args()
    if a.warmup < 5 or a.runs < 5 or a.tokens < 128 or a.paragraphs < 1:
        p.error("require at least 5 warmup, 5 runs, 128 output tokens and 1 paragraph")
    cfg = json.loads(a.config.read_text(encoding="utf-8"))
    custom_prompt=a.prompt_file.read_text(encoding='utf-8').strip() if a.prompt_file else None
    if a.prompt_file and (not custom_prompt or len(custom_prompt)>6000):p.error('custom prompt must contain 1..6000 characters')
    if a.interleave_minp:
        for flag in ('--prompt-cache','--conversation-cache-mib'):
            if flag not in cfg['args'] or cfg['args'][cfg['args'].index(flag)+1]!='0':raise RuntimeError('Interleaved paired prompts require cache disabled')
        if a.runs%2:raise RuntimeError('Require even pair count for balanced AB/BA order')
    log = Path(cfg["log"])
    headers = {"Content-Type": "application/json"}
    if os.environ.get("STRATA_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["STRATA_API_KEY"]
    def get(path):
        with urllib.request.urlopen(urllib.request.Request(a.url.rstrip("/")+path, headers=headers), timeout=30) as r:
            return json.load(r)
    status = get("/metrics")
    if status["live"]["state"] not in ("idle", "unloaded") or status["live"].get("queued"):
        raise RuntimeError("Server busy: benchmark would be invalid")
    if not status["diagnostics"]["config_fingerprint"] == config_fingerprint(cfg):
        raise RuntimeError("Server configuration differs from benchmark configuration; restart server first")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    lock = a.output.parent / ".benchmark.lock"
    report = {"schema_version": 1, "label": a.label, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
              "config_fingerprint": config_fingerprint(cfg), "engine": status["engine"],
              "hardware": status["hardware_static"], "protocol": {"warmup":a.warmup,"runs":a.runs,"tokens":a.tokens,"paragraphs":a.paragraphs,"prompt_set":a.prompt_set},
              "rows": [], "status": "running"}
    if a.interleave_minp:report['protocol'].update(interleaved=True,settings=[0.5,0.7],order='alternating AB/BA pairs',prompt_cache=False)
    binary = Path(cfg["exe"])
    with binary.open("rb") as f:
        report["binary_sha256"] = hashlib.file_digest(f, "sha256").hexdigest()
    # Exclusive creation prevents a second benchmark in this workspace from sharing the GPU.
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd,'w') as stream:stream.write(str(os.getpid()))
    try:
        atomic_json(a.output, report)
        count=(a.warmup+a.runs)*(2 if a.interleave_minp else 1)
        for i in range(count):
            pair=i//2 if a.interleave_minp else i
            threshold=([0.5,0.7] if pair%2==0 else [0.7,0.5])[i%2] if a.interleave_minp else None
            if a.stop_file and a.stop_file.exists():raise InterruptedError('Arresto richiesto fra le richieste')
            if i == 0 and status["live"]["state"] == "unloaded":
                # Lazy server must first load the model; this request is never measured.
                body = {"model":cfg["model_name"],"messages":[{"role":"user","content":"Rispondi pronto."}],"max_tokens":1,"reasoning_effort":"none"}
                with urllib.request.urlopen(urllib.request.Request(a.url+"/v1/chat/completions",data=json.dumps(body).encode(),headers=headers),timeout=1200) as r:
                    json.load(r)
            st = log.stat()
            offset, identity = st.st_size, (st.st_dev, st.st_ino)
            nonce = hashlib.sha256(f"{a.prompt_set}:{pair}".encode()).hexdigest()[:32]
            prompt = f"Caso {nonce}:\n"+(custom_prompt if custom_prompt is not None else PARAGRAPH*a.paragraphs+"\nScrivi un'analisi ampia con esempi tecnici.")
            body = {"model":cfg["model_name"],"messages":[{"role":"user","content":prompt}],
                    "max_tokens":a.tokens,"temperature":0,"top_k":1,"top_p":1,"min_p":0,"seed":42,"reasoning_effort":"none"}
            if threshold is not None:body['strata_tune']={'spec_min_p':threshold}
            start = time.perf_counter()
            with urllib.request.urlopen(urllib.request.Request(a.url.rstrip("/")+"/v1/chat/completions",data=json.dumps(body,ensure_ascii=False).encode(),headers=headers),timeout=1200) as r:
                data = json.load(r)
            wall = time.perf_counter()-start
            deadline = time.monotonic()+5
            while True:
                timings = new_timings(log,offset,identity)
                if timings or time.monotonic() >= deadline:
                    break
                time.sleep(.05)
            if len(timings) != 1:
                raise RuntimeError(f"Expected one completed timing line, got {len(timings)}")
            row = dict(zip(FIELDS,map(float,timings[0])))
            if row["reused"] != 0 or row["generated"] <= 0 or row["decode_ms"] <= 0:
                raise RuntimeError("Cached prompt or invalid engine timing: arm invalid")
            choice = data["choices"][0]
            if choice.get("finish_reason") not in ("stop","length") or not choice.get("message",{}).get("content"):
                raise RuntimeError("No usable model answer")
            row.update(warmup=pair<a.warmup,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),wall_s=wall,wall_tok_s=data["usage"]["completion_tokens"]/wall,
                       output_tokens=data["usage"]["completion_tokens"],finish_reason=choice["finish_reason"],
                       response_sha256=hashlib.sha256(choice["message"]["content"].encode()).hexdigest())
            if threshold is not None:
                if row['generated']!=a.tokens or row['output_tokens']!=a.tokens:raise RuntimeError('Incomplete output in paired experiment')
                row.update(pair=pair,spec_min_p=threshold,order=i%2)
            report["rows"].append(row)
            report["summary"] = summarize(report["rows"])
            atomic_json(a.output,report)
            print(f"{'warmup' if row['warmup'] else 'measure'} {i+1}: decode {row['decode_tok_s']:.1f}, wall {row['wall_tok_s']:.1f} tok/s",flush=True)
        if a.interleave_minp:
            measured=[r for r in report['rows'] if not r['warmup']]
            settings={str(value):summarize([r for r in measured if r['spec_min_p']==value]) for value in (0.5,0.7)}
            deltas=[]
            for pair in sorted({r['pair'] for r in measured}):
                rows={r['spec_min_p']:r for r in measured if r['pair']==pair}
                if set(rows)!={0.5,0.7} or rows[0.5]['prompt_sha256']!=rows[0.7]['prompt_sha256']:raise RuntimeError('Unpaired prompts')
                deltas.append((rows[0.7]['decode_tok_s']/rows[0.5]['decode_tok_s']-1)*100)
            report['paired_comparison']=dict(settings=settings,paired_changes_percent=deltas,median_paired_change_percent=statistics.median(deltas),candidate_wins=sum(x>0 for x in deltas),pairs=len(deltas),promotion=False)
        report["status"] = "complete"
        report["engine"] = get("/metrics")["engine"]
    except BaseException as e:
        report["status"], report["error"] = ('cancelled' if isinstance(e,InterruptedError) else 'failed'), str(e)
        raise
    finally:
        atomic_json(a.output,report)
        lock.unlink(missing_ok=True)
    print(json.dumps(report["summary"],indent=2))


if __name__ == "__main__":
    main()
