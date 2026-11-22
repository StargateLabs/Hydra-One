"""Summarize native window diagnostics; overlapping timings are never added."""
import argparse
import json
from pathlib import Path
import re
import statistics
ROOT=Path(__file__).resolve().parents[1]
PATTERN=re.compile(r'strata decode timing: (\d+) windows, avg T ([\d.]+), ([\d.]+) tokens/window, ([\d.]+) ms/window = verify ([\d.]+) \(GPU-reach wait ([\d.]+) \+ per-layer host ([\d.]+) \[plan ([\d.]+) actq ([\d.]+) jobs ([\d.]+) CPU ([\d.]+)\]')
FIELDS=('windows','draft_window','useful_tokens_per_window','window_ms','verify_ms','gpu_reach_wait_ms','host_ms','plan_ms','activation_quant_ms','dispatch_ms','cpu_experts_ms')
def analyze(path):
    samples=[]
    for lineno,line in enumerate(path.read_text(encoding='utf-8',errors='replace').splitlines(),1):
        match=PATTERN.search(line)
        if match:samples.append(dict(zip(FIELDS,map(float,match.groups())),line=lineno))
    if not samples:raise ValueError('No native window diagnostics: '+str(path))
    medians={key:statistics.median(row[key] for row in samples) for key in FIELDS}
    return dict(source=path.relative_to(ROOT).as_posix(),samples=len(samples),medians=medians,
        target_100_window_ms_at_same_useful_tokens=medians['useful_tokens_per_window']*10,
        scope='All logged diagnostics, including warmups; rounded values, not the measured ABBA median. GPU and CPU timings overlap; never add or treat wait time as independently removable.',
        observations=samples)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--stamp',required=True);parser.add_argument('--feature',required=True);args=parser.parse_args()
    paths=sorted((ROOT/'output/verification').glob(f'{args.stamp}-iq3-memory-{args.feature}*-engine.log'))
    if len(paths)!=4:raise SystemExit('Expected four ABBA engine logs')
    result=dict(stamp=args.stamp,feature=args.feature,arms=[analyze(p) for p in paths])
    target=ROOT/f'output/verification/{args.stamp}-{args.feature}-decode-path.json';target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([dict(source=x['source'],samples=x['samples'],medians=x['medians'],target_window_ms=x['target_100_window_ms_at_same_useful_tokens']) for x in result['arms']],indent=2))
