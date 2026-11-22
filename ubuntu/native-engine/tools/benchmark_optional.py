"""Controlled optional GGUF ABBA; records are separate from flagship Strata."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from verify_optional_real import call,wait_ready,ROOT
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',required=True,type=Path)
    parser.add_argument('--runs',default=5,type=int,choices=range(5,11))
    args=parser.parse_args()
    if call('/inference-backends')['status']!='idle' or call('/metrics')['live']['state']!='unloaded':raise RuntimeError('Both backends must be unloaded')
    stamp=time.strftime('%Y%m%d-%H%M%S',time.gmtime());started_at=time.time()
    report=dict(kind='backend_check',id=stamp+'-optional-abba',started_at=started_at,model_file=str(args.model.resolve()),status='running',protocol=dict(warmup=1,runs=args.runs,tokens=128,cache_prompt=False),runs=[],scope='Optional GGUF only; excluded from 125B record',promotion=False)
    directory=ROOT/'data/benchmark-checks';directory.mkdir(parents=True,exist_ok=True)
    path=directory/(report['id']+'.json')
    from serve.configuration import atomic_json
    for arm,profile in [('A1','balanced'),('B1','rocm'),('B2','rocm'),('A2','balanced')]:
        try:
            call('/inference-backends/start',dict(mode='gguf',model_path=str(args.model.resolve()),gpu=True,profile=profile))
            state=wait_ready();model=state['public_model']
            request=dict(model=model,messages=[dict(role='user',content='Return only the number: 7 + 5 = ?')],max_tokens=128,temperature=0,stream=False,chat_template_kwargs=dict(enable_thinking=False),cache_prompt=False)
            answer=call('/v1/chat/completions',request)['choices'][0]['message'].get('content','')
            rows=[]
            for index in range(args.runs+1):
                request['messages']=[dict(role='user',content='Write a detailed continuous story of at least 800 words about a traveller. Do not conclude early. Background facts: '+('The traveller follows the coast, visits a library and learns about the night sky. '*50))]
                request_started=time.monotonic()
                result=call('/v1/chat/completions',request);wall_s=time.monotonic()-request_started;timings=result.get('timings') or {};usage=result.get('usage') or {}
                count=usage.get('completion_tokens');speed=timings.get('predicted_per_second');prompt_speed=timings.get('prompt_per_second')
                if count!=128 or not isinstance(speed,(int,float)) or speed<=0 or timings.get('cache_n')!=0:raise RuntimeError('Invalid token budget, speed or prompt-cache reuse; no comparable result')
                rows.append(dict(warmup=index==0,output_tokens=count,decode_tok_s=speed,prefill_tok_s=prompt_speed,wall_s=wall_s,model_time_s=(timings['predicted_ms']+timings['prompt_ms'])/1000))
            measured=rows[1:]
            report['runs'].append(dict(arm=arm,profile=profile,gpu_requested=True,public_model=model,rows=rows,arithmetic_check=dict(expected='12',answer=answer,passed=answer.strip()=='12'),summary={key:statistics.median(row[key] for row in measured) for key in ('decode_tok_s','prefill_tok_s','wall_s')}))
            atomic_json(path,report)
        except Exception as error:
            report.update(status='failed',error=str(error));atomic_json(path,report);raise
        finally:call('/inference-backends/stop',{})
    control=[row for arm in report['runs'] if arm['profile']=='balanced' for row in arm['rows'] if not row['warmup']]
    candidate=[row for arm in report['runs'] if arm['profile']=='rocm' for row in arm['rows'] if not row['warmup']]
    baseline=statistics.median(r['decode_tok_s'] for r in control);optimized=statistics.median(r['decode_tok_s'] for r in candidate)
    drift=100*(report['runs'][3]['summary']['decode_tok_s']/report['runs'][0]['summary']['decode_tok_s']-1)
    report.update(status='complete',finished_at=time.time(),pooled=dict(control=baseline,candidate=optimized,change_percent=100*(optimized/baseline-1)),control_drift_percent=drift,confounded=abs(drift)>5,limitations='One ABBA, one arithmetic quality check; not endurance or general quality validation')
    atomic_json(path,report);print(json.dumps({k:report[k] for k in ('id','status','pooled','control_drift_percent','confounded','promotion')},indent=2))

if __name__=='__main__':main()
