"""Offline HC contract audit. Never imports a GPU runtime or launches a process.

Passing arithmetic/source checks is not numerical validation or a crash diagnosis.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def audit():
    source = ROOT / 'output/research/source-hc-small-window-01403/src/kernels/cuda/fused_gr.cu'
    body = source.read_text(encoding='utf-8')
    incident = json.loads((ROOT / 'output/verification/hc-small-gpu-incident.json').read_text())
    rows = []
    for tokens in range(1, 7):
        # S=1; PR=320 down rows + 4 injection rows. Caller reserves S=2 space.
        partial_end = tokens * 4 * 324
        sums_start = tokens * 4 * 2 * 324
        sums_end = sums_start + tokens * 4
        scratch_capacity = tokens * 4 * 2560
        dynamic_lds = tokens * 2560 * 4
        static_lds = 8 * tokens * 4  # red[WARPS][MAX_T], THREADS=256
        rows.append(dict(tokens=tokens,partial_end_float=partial_end,
            sums_start_float=sums_start,sums_end_float=sums_end,
            scratch_capacity_float=scratch_capacity,
            disjoint_and_within_capacity=partial_end<=sums_start and sums_end<=scratch_capacity,
            lds_bytes=dynamic_lds+static_lds,within_64k=dynamic_lds+static_lds<=65536,
            exact_down_dispatch=f'gr_down_v3_kernel<1, {tokens}, true><<<' in body,
            exact_up_dispatch=f'gr_up_v3_kernel<1, {tokens}, true><<<' in body))
    checks=dict(window_and_q8_gate='n_tok >= 1 && n_tok <= 6 && !q8' in body,
        same_stream='THREADS, sm, st>>>' in body and 'THREADS, 0, st>>>' in body,
        quarantine=incident.get('status')=='quarantined' and incident.get('no_automatic_retry') is True)
    binary=ROOT/'engine/strata.exe'
    if binary.is_file():
        checks['installed_binary_unchanged']=hashlib.sha256(binary.read_bytes()).hexdigest()==incident['installed_engine_sha256']
    return dict(scope='Offline source and arithmetic checks only; no GPU execution',
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),checks=checks,windows=rows,
        passed=all(checks.values()) and all(all(r[k] for k in ('disjoint_and_within_capacity','within_64k','exact_down_dispatch','exact_up_dispatch')) for r in rows),
        root_cause_confirmed=False,
        unresolved=['Runtime pointer validity and lifetime','Graph replay dependencies',
                    'In-place alias parity under repeated requests','Actual compiled kernel resource usage'])

if __name__=='__main__':
    result=audit()
    target=ROOT/'output/verification/hc-contract-audit-20261010.json'
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
