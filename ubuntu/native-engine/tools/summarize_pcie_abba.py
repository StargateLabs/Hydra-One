"""Validate the isolated automatic-versus-55-percent PCIe experiment."""
import json
import math
import re
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
NAMES=('pcie-auto-a1','pcie55-b1','pcie55-b2','pcie-auto-a2')

def summarize(stamp,percent=55):
    assert percent in (20,55)
    names=('pcie-auto-a1',f'pcie{percent}-b1',f'pcie{percent}-b2','pcie-auto-a2')
    reports=[];configs=[];groups=[]
    for index,name in enumerate(names):
        report=json.loads((ROOT/f'data/benchmarks/{stamp}-iq3-memory-{name}.json').read_text())
        config=json.loads((ROOT/f'output/verification/{stamp}-iq3-memory-{name}.json').read_text())
        assert report['status']=='complete' and len(report['rows'])==10
        assert report['engine']['vram_free_mib']>=1536
        effective=float(report['engine']['pcie_frac'])
        assert math.isfinite(effective) and 0<=effective<=1
        if index in (1,2):assert abs(effective-percent/100)<0.005
        else:assert effective<0.55 and (percent!=20 or effective>0.20)
        assert report['protocol']['tokens']==256 and report['protocol']['warmup']==report['protocol']['runs']==5
        args=list(config['args'])
        if index in (1,2):
            i=args.index('--pcie-frac');assert args[i+1]==f'{percent/100:.2f}';del args[i:i+2]
        else:assert '--pcie-frac' not in args
        if configs:
            assert args==configs[0]['args'] and config['env']==configs[0]['env']
            assert report['binary_sha256']==reports[0]['binary_sha256'] and report['protocol']==reports[0]['protocol']
            assert report['engine']['expert_slots']==reports[0]['engine']['expert_slots']
            assert report['engine']['model']==reports[0]['engine']['model']
            assert [r['prompt_sha256'] for r in report['rows']]==[r['prompt_sha256'] for r in reports[0]['rows']]
        assert [r['warmup'] for r in report['rows']]==[True]*5+[False]*5
        assert all(r['output_tokens']==256 and r['reused']==0 for r in report['rows'])
        group=report['rows'][5:]
        assert all(math.isfinite(r[k]) and r[k]>0 for r in group for k in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s'))
        reports.append(report);configs.append(config);groups.append(group)
    metrics=('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s');pooled={}
    for key in metrics:
        control=statistics.median(r[key] for i in (0,3) for r in groups[i]);candidate=statistics.median(r[key] for i in (1,2) for r in groups[i])
        pooled[key]=dict(control=control,candidate=candidate,change_percent=(candidate/control-1)*100)
    split=[]
    for name in names:
        log_path=ROOT/f'output/verification/{stamp}-iq3-memory-{name}-engine.log'
        log=log_path.read_text(encoding='utf-8') if log_path.is_file() else ''
        records=re.findall(r'strata decode timing: .*?([\d.]+) tokens/window, ([\d.]+) ms/window = verify .*?GPU-reach wait ([\d.]+) \+ per-layer host ([\d.]+) \[plan [\d.]+ actq [\d.]+ jobs ([\d.]+) CPU ([\d.]+)\]',log)
        if len(records)==10:
            measured=[tuple(map(float,r)) for r in records[5:]]
            split.append({key:statistics.median(row[index]/row[0] for row in measured) for key,index in
                (('window_ms_per_output_token',1),('gpu_reach_wait_ms_per_output_token',2),
                 ('host_ms_per_output_token',3),('job_dispatch_ms_per_output_token',4),('cpu_experts_ms_per_output_token',5))})
        else:split.append(None)
    result=dict(status='complete',stamp=stamp,measured_at=reports[0]['started_at'],model=reports[0]['engine']['model'],
        binary_sha256=reports[0]['binary_sha256'],protocol=reports[0]['protocol'],expert_slots=reports[0]['engine']['expert_slots'],
        pooled=pooled,arm_medians={name:{k:statistics.median(r[k] for r in g) for k in metrics} for name,g in zip(names,groups)},
        effective_pcie_share=[r['engine'].get('pcie_frac') for r in reports],measured_requests=20,warmup_requests=20,
        split_diagnostics=dict(zip(names,split)),split_diagnostics_note='Overlapping timings; never add host and GPU waits. Normalized by rounded useful tokens/window.',
        promotion=False,limitations='One ABBA; allocation can change CPU/GPU rounding; independent quality and endurance pending')
    result['candidate_percent']=percent
    (ROOT/f'output/verification/{stamp}-pcie{percent}-abba-summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2));return result

if __name__=='__main__':summarize(sys.argv[1])
