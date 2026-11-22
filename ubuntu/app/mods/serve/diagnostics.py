"""Read-only operational checks. No prompts, credentials or configuration paths are returned."""
import hashlib
import json
import math
from pathlib import Path
from serve.lab_metrics import measured_series


def config_fingerprint(cfg):
    selected = {k: cfg.get(k) for k in ("exe", "args", "env", "backend", "model_name")}
    return hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()


def diagnose(cfg, engine, hardware, loaded, vision):
    checks = []
    args = cfg.get("args") or []
    def flag(name):
        try:
            return args[args.index(name) + 1]
        except (ValueError, IndexError):
            return None
    def add(key, state, title, detail):
        checks.append(dict(id=key, state=state, title=title, detail=detail))
    add("engine", "ok" if loaded else "info", "Motore",
        "Caricato e disponibile." if loaded else "Scaricato: la prossima richiesta può caricarlo.")
    add("vision", "ok" if vision else "info", "Immagini",
        "Encoder attivo." if vision else "Encoder spento; attivalo da Control quando serve.")
    budget = flag("--resident-budget-gib")
    if budget is not None:
        add("resident", "info", "Cache esperti RAM",
            f"Budget configurato: {budget} GiB al caricamento. Il motore verifica il margine disponibile; "
            "il budget configurato non certifica da solo la quantità effettivamente allocata.")
    if loaded:
        pending = []
        for option, field in (("--max-context", "max_context"), ("--kv-resident", "kv_resident")):
            configured, active = flag(option), engine.get(field)
            if configured is not None and active is not None and str(configured) != str(active):
                pending.append(f"{field}: attivo {active}, salvato {configured}")
        if pending:
            add("restart", "warn", "Riavvio richiesto", "; ".join(pending))
    table = (cfg.get("env") or {}).get("STRATA_HIPBLASLT_TUNING")
    if table:
        path = Path(cfg.get("cwd") or ".") / table
        add("tuning", "ok" if path.is_file() else "warn", "Tabella hipBLASLt",
            "Tabella configurata e presente; l'accettazione dipende dal runtime."
            if path.is_file() else "La tabella configurata manca: il motore userà il fallback.")
    for key, used, total, title in (("ram", "ram_used", "ram_total", "RAM"),
                                   ("vram", "gpu_mem_used", "gpu_mem_total", "VRAM")):
        u, t = hardware.get(used), hardware.get(total)
        if u is None or not t:
            add(key, "unknown", title, "Lettura non disponibile.")
        else:
            free = max(0, t-u) / 2**30
            add(key, "warn" if u/t >= .95 else "ok", title, f"{free:.1f} GiB disponibili · {100*u/t:.0f}% in uso.")
    add("power", "info", "Soglie termiche", "Avvisi software: non modificano potenza, clock o limiti del driver.")
    if flag("--expert-profile-save") and not any(x in args for x in ("--resident-experts", "--resident-cpu-experts")):
        add("profile", "warn", "Profilo esperti", "Salvataggio richiesto senza esperti residenti: questo percorso può non produrre il file.")
    return {"checks": checks, "config_fingerprint": config_fingerprint(cfg),
            "warnings": sum(c["state"] == "warn" for c in checks),
            "measurement": "live.tok_s: finestra di consegna; requests.decode_tok_s: protocollo DONE; benchmark: log motore e tempo totale separati"}


def benchmark_reports(root):
    reports = []
    directory = Path(root) / "data" / "benchmarks"
    candidates = []
    for p in directory.glob("*.json"):
        try:
            candidates.append((p.stat().st_mtime, p))
        except OSError:
            continue
    for _, p in sorted(candidates, reverse=True)[:1000]:
        try:
            if p.stat().st_size > 2**20:
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("schema_version") != 1:
                continue
            record={k:d.get(k) for k in ("label","started_at","status","config_fingerprint","binary_sha256","protocol","summary","origin","quality_gate")}
            rows=d.get('rows') or [];protocol=d.get('protocol') or {};measured=[row for row in rows if isinstance(row,dict) and row.get('warmup') is False]
            if d.get('status')=='complete' and type(protocol.get('runs')) is int and 0<protocol['runs']<=100 and len(measured)==protocol['runs']:
                record['sample_series']=measured_series(measured)
            record.update(model=(d.get('engine') or {}).get('model'),samples=len(rows))
            if d.get('publisher')=='hydra-benchmark-registry-v2':record.update(hydra_run_id=d.get('run_id'),source=d.get('source_artifacts'))
            reports.append(record)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return {"reports":reports,"persistent":True}
