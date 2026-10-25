"""Extract completed profiler observations, keeping overlapping timings separate."""
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

def summarize(stamp):
    label = f'{stamp}-iq3-memory-head-profile'
    log = (ROOT/f'output/verification/{label}-engine.log').read_text(encoding='utf-8')
    matrix = json.loads((ROOT/f'output/verification/{label}/{label}/matrix.json').read_text())
    if len(matrix) != 2 or any(r.get('error') or r.get('completion_tokens') != 256 for r in matrix):
        raise ValueError('Incomplete profiler requests')
    timings = re.findall(r'strata decode timing: .*?([\d.]+) ms/window = verify .*?\+ draft ([\d.]+);',log)
    heads = re.findall(r'strata decode GPU stages .*? head ([\d.]+).*?total ([\d.]+) ms/window',log)
    if len(timings) != 2 or len(heads) != 2:
        raise ValueError('Missing profiler measurements')
    rows = []
    for (window,draft),(head,gpu) in zip(timings,heads):
        window,draft,head,gpu = map(float,(window,draft,head,gpu))
        rows.append(dict(window_ms=window,verifier_head_ms=head,draft_total_ms=draft,gpu_stages_ms=gpu,
            verifier_head_share_percent=100*head/window,
            impossible_zero_head_upper_bound_gain_percent=100*(window/(window-head)-1)))
    result = dict(status='complete',kind='Instrumented diagnostic; not comparable to uninstrumented speed benchmark',
        stamp=stamp,rows=rows,
        limitation='Draft total includes all draft operations, not just its head. GPU and host timings overlap; do not sum them.',
        source=f'output/verification/{label}-engine.log',promotion=False)
    (ROOT/f'output/verification/{stamp}-head-profile-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result

if __name__ == '__main__':
    summarize(sys.argv[1])
