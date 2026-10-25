"""Import measured optional-backend runs without mixing model identities."""
import json
import math
import statistics
from pathlib import Path
from datetime import datetime, timezone
from serve.lab_metrics import measured_series,GENERATION_SCOPE

def reports(root):
    result=[]
    for path in sorted((Path(root)/'data/benchmark-checks').glob('*.json'),reverse=True)[:100]:
        try:
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            if data.get('verification_fixture'):continue
            protocol=data['protocol']
            if data.get('status')!='complete':continue
            for arm in data['runs']:
                rows=[row for row in arm.get('rows',[]) if row.get('warmup') is False]
                warm=[row for row in arm.get('rows',[]) if row.get('warmup') is True]
                if len(rows)!=protocol['runs'] or len(warm)!=protocol['warmup'] or not arm.get('public_model'):continue
                full_budget=all(row.get('output_tokens')==protocol['tokens'] for row in rows+warm)
                if not full_budget and protocol.get('output_policy')!='actual_output':continue
                if any(row.get('output_tokens') is not None and (type(row['output_tokens']) is not int or row['output_tokens']<=0 or row['output_tokens']>protocol['tokens']) for row in rows+warm):continue
                summary={}
                for metric in ('decode_tok_s','prefill_tok_s','generation_ms','ttft_s'):
                    if metric=='generation_ms' and any(row.get('timing_scope')!=GENERATION_SCOPE for row in rows):continue
                    values=[row.get(metric) for row in rows]
                    if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in values):continue
                    summary[metric]=dict(min=min(values),max=max(values),median=statistics.median(values))
                # End-to-end throughput is only available when API wall time was recorded.
                walls=[row.get('wall_s') for row in rows]
                if all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in walls):
                    speeds=[row['output_tokens']/v for row,v in zip(rows,walls)] if all(type(row.get('output_tokens')) is int for row in rows) else []
                    if speeds:summary['wall_tok_s']=dict(min=min(speeds),max=max(speeds),median=statistics.median(speeds))
                    summary['wall_s']=dict(min=min(walls),max=max(walls),median=statistics.median(walls))
                if not summary:continue
                native_colibri=data.get('publisher')=='colibri' or arm['public_model']=='local/qwen3.6-colibri'
                result.append(dict(model=arm['public_model'],backend='Colibri' if native_colibri else data.get('backend','llama.cpp'),status='complete',
                    label=f"{data['id']} · {arm['arm']} · {arm['profile']}",
                    started_at=datetime.fromtimestamp(data['started_at'],timezone.utc).isoformat(),
                    protocol={**protocol,'prompt_set':None,'full_budget':full_budget},summary=summary,source=path.name,
                    sample_series=measured_series(rows)))
        except (OSError,ValueError,TypeError,KeyError):continue
    return result

def best_groups(rows,model):
    groups={}
    for row in rows:
        if row['protocol'].get('single_cold_sample'):continue
        if row['model']!=model or row['protocol'].get('full_budget') is False:continue
        metric=next((key for key in ('decode_tok_s','wall_tok_s') if key in row['summary']),None)
        if metric is None:continue
        key=row['source'];p=row['protocol'];s=row['summary']
        candidate=dict(job_id=key,label=row['label'],summary={metric:values['median'] for metric,values in s.items()},
                       finished_at=datetime.fromisoformat(row['started_at']).timestamp(),ranking_metric=metric)
        group=groups.setdefault(key,dict(id=key,model=model,protocol=p,tested_profiles=0,winner=candidate))
        group['tested_profiles']+=1
        if candidate['summary'][metric]>group['winner']['summary'][metric]:group['winner']=candidate
    return list(groups.values())
