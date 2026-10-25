"""Summarize engine decode phases without mixing prefill or overlapping timers."""
import argparse
import json
from pathlib import Path
import re
import statistics
import math

TIMING = re.compile(r'strata decode timing: (\d+) windows, avg T ([\d.]+), ([\d.]+) tokens/window, ([\d.]+) ms/window = verify ([\d.]+) \(GPU-reach wait ([\d.]+) \+ per-layer host ([\d.]+) \[plan ([\d.]+) actq ([\d.]+) jobs ([\d.]+) CPU ([\d.]+)\] \+ stage ([\d.]+)\) \+ commit/emit ([\d.]+) \+ draft ([\d.]+)')
FIELDS=('windows','draft_window','tokens_per_window','window_ms','verify_ms','gpu_reach_wait_ms','host_ms','plan_ms','activation_quant_ms','jobs_ms','cpu_ms','staging_ms','commit_ms','draft_ms')
GPU_STAGES=('q8+qkv/q-idx gemv','conv','ab','z','rec','q8+kv-idx','k/v+norm-rope','kv+idx append','q+q-idx','scores+topk','kv-resolve','attention','gate','out-proj','hc-read1+router','shared+quant','waitA','VRAM hits','waitB','PCIe grp','waitCPU','copy+combine','(gap)','head','hc0 norm','hc0 down','hc0 up')

def gpu_stages(text,warmup):
    records=[]
    for line in text.splitlines():
        if not line.startswith('strata decode GPU stages (ms/window):'):continue
        sections=line.split('GDN layers:',1)[-1].split(' | QSA layers:')
        if len(sections)!=2:continue
        row={}
        for kind,section in zip(('gdn','qsa'),sections):
            for stage in GPU_STAGES:
                match=re.search(r'(?:^|\s)'+re.escape(stage)+r' ([\d.]+)(?=\s|$)',section)
                if match:row[kind+':'+stage]=float(match[1])
        records.append(row)
    measured=records[warmup:]
    if not measured:return None
    keys=set.intersection(*(set(row) for row in measured))
    return dict(measured_requests=len(measured),median_ms_per_window={key:statistics.median(row[key] for row in measured) for key in sorted(keys)},
                scope='GPU timestamp stages; waits can include host work. Instrumentation can perturb execution.')

def analyze(text, warmup=5, target=100):
    if not isinstance(warmup,int) or warmup<0:raise ValueError('warmup must be a nonnegative integer')
    if not math.isfinite(target) or target<=0:raise ValueError('target must be finite and positive')
    rows=[dict(zip(FIELDS,map(float,match))) for match in TIMING.findall(text)]
    measured=rows[warmup:]
    if not measured:raise ValueError('No measured decode phase records after warmup')
    if any(row['window_ms']<=0 or row['tokens_per_window']<=0 for row in measured):raise ValueError('Invalid decode timing')
    for row in measured:
        row['target_window_ms']=1000*row['tokens_per_window']/target
        row['window_reduction_required_percent']=100*(1-row['target_window_ms']/row['window_ms'])
        row['tokens_required_at_current_latency']=target*row['window_ms']/1000
    # Individual optimistic counterfactuals only: nested timings must never be summed.
    sensitivity={}
    for phase in ('host_ms','draft_ms','commit_ms'):
        scenarios=[]
        for row in measured:
            remaining=row['window_ms']-row[phase]
            if remaining<=0:raise ValueError('Phase timing exceeds the window duration')
            scenarios.append(1000*row['tokens_per_window']/remaining)
        sensitivity[phase]={
            'median_optimistic_decode_tok_s':statistics.median(scenarios),
            'all_requests_reach_target':all(value>=target for value in scenarios)}
    return dict(status='complete',target_decode_tok_s=target,warmup_excluded=warmup,measured_requests=len(measured),gpu_stages=gpu_stages(text,warmup),
        single_phase_elimination=sensitivity,
        medians={key:statistics.median(row[key] for row in measured) for key in measured[0]},
        rows=measured,limitations=['Engine phase timers are nested and can overlap; do not add CPU and GPU wait as independent costs.',
                                  'Latency budget assumes unchanged tokens accepted per window; it is a diagnostic, not a speed prediction.',
                                  'Single-phase elimination assumes its entire measured time lies on the critical path. It is optimistic, not a measured gain; scenarios cannot be combined.',
                                  'Decode excludes prefill and HTTP wall time; correctness is evaluated separately.'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--log',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--warmup',type=int,default=5)
    parser.add_argument('--target',type=float,default=100)
    args=parser.parse_args()
    if args.warmup<0:parser.error('warmup must be nonnegative')
    result=analyze(args.log.read_text(encoding='utf-8',errors='replace'),args.warmup,args.target)
    result['source_log']=str(args.log.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['medians'],indent=2))

if __name__=='__main__':main()
