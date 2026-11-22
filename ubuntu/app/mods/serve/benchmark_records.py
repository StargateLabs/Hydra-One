"""Best observed medians, grouped by protocol and common configuration.

Reads completed raw reports; an unfinished job can never become a record.
Different nonce prompts still prevent treating these records as a causal ABBA.
"""
import hashlib
import json
import math
from pathlib import Path
import statistics
import re

def best_groups(root,model):
    root=Path(root);groups={}
    for path in sorted((root/'data/benchmark-lab').glob('*/job.json')):
        try:
            job=json.loads(path.read_text(encoding='utf-8-sig'))
            if job.get('status')!='complete':continue
            protocol=job['protocol'];identity=job['id']
            if path.parent.name!=identity:continue
            for result in job['results']:
                variant=result['variant']
                if variant not in ('auto','pcie20','pcie55','tsum'):continue
                source=f'data/benchmarks/lab-{identity}-{variant}.json'
                if result['source']!=source:continue
                report=json.loads((root/source).read_text(encoding='utf-8-sig'));raw=report['protocol'];rows=report['rows']
                if report['status']!='complete' or report['engine']['model']!=model:continue
                if not re.fullmatch('[a-f0-9]{64}',report.get('binary_sha256','')):continue
                if any(raw[k]!=protocol[k] for k in ('tokens','runs','paragraphs')) or raw['warmup']!=5 or len(rows)!=5+protocol['runs']:continue
                if any(r['reused']!=0 or r['output_tokens']!=protocol['tokens'] or r['warmup']!=(i<5) for i,r in enumerate(rows)):continue
                measures=rows[5:];summary={}
                for metric in ('decode_tok_s','prefill_tok_s','wall_s'):
                    values=[r[metric] for r in measures]
                    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values):raise ValueError('Invalid measurement')
                    summary[metric]=statistics.median(values)
                cfg=json.loads((path.parent/f'{variant}-config.json').read_text(encoding='utf-8-sig'));args=list(cfg['args'])
                if '--pcie-frac' in args:i=args.index('--pcie-frac');del args[i:i+2]
                cfg['args']=args;cfg.get('env',{}).pop('STRATA_TSUM',None)
                for key in ('log','benchmark_owner'):cfg.pop(key,None)
                fingerprint=dict(protocol={k:v for k,v in protocol.items() if k not in ('variants','quality','mode')},
                    prompt_sha256=job['prompt_sha256'],binary_sha256=report['binary_sha256'],config=cfg)
                group_id=hashlib.sha256(json.dumps(fingerprint,sort_keys=True).encode()).hexdigest()
                candidate=dict(job_id=identity,variant=variant,label=result['label'],summary=summary,quality=result.get('quality'),
                    source=source,finished_at=job['finished_at'])
                group=groups.setdefault(group_id,dict(id=group_id,protocol={k:protocol[k] for k in ('tokens','paragraphs','runs')},
                    model=model,latest_at=job['finished_at'],tested_profiles=0,winner=candidate))
                group['tested_profiles']+=1;group['latest_at']=max(group['latest_at'],job['finished_at'])
                if summary['decode_tok_s']>group['winner']['summary']['decode_tok_s']:group['winner']=candidate
        except (OSError,ValueError,KeyError,TypeError,IndexError):continue
    return sorted(groups.values(),key=lambda g:g['latest_at'],reverse=True)
