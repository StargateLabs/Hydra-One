"""One small-model GPU request through the dashboard, always unload afterwards."""
import json,time,argparse
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8088'
def call(path,body=None):
    request=Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=45) as response:return json.load(response)
report=dict(kind='backend_check',id=time.strftime('%Y%m%d-%H%M%S')+'-safetensors-gpu',
            started_at=time.time(),scope='One SmolLM2-135M GPU FP16 request, 1K context and 8 output tokens; not a 125B or stability benchmark',passed=False)
parser=argparse.ArgumentParser();parser.add_argument('--benchmark',action='store_true');parser.add_argument('--loader',choices=('transformers','unsloth'),default='transformers');args=parser.parse_args()
report['loader']=args.loader
report['id']+='-'+args.loader
started=False
try:
    if call('/inference-backends')['status']!='idle' or call('/metrics')['live']['state']!='unloaded':raise RuntimeError('An engine is already active')
    model=Path(json.loads((ROOT/'output/verification/chat-regenerate-safetensors-real.json').read_text(encoding='utf-8'))['path'])
    report['model_path']=str(model)
    call('/inference-backends/start',dict(mode='safetensors',model_path=str(model),gpu=True,context=1024,fit_mode='manual',context_mode='manual',runtime=dict(threads=2,python_loader=args.loader)));started=True
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        state=call('/inference-backends')
        if state['status']=='error':raise RuntimeError(state['error'])
        if state['status']=='ready':break
        time.sleep(.25)
    else:raise RuntimeError('Small model load exceeded 90 seconds')
    deadline=time.monotonic()+6
    while not state.get('gpu_process_resources') and time.monotonic()<deadline:
        time.sleep(.25);state=call('/inference-backends')
    if state.get('native_loader')!=args.loader:raise RuntimeError('Requested loader was not confirmed')
    report['backend']=state
    if not state.get('gpu_process_resources'):raise RuntimeError('Owned GPU memory telemetry unavailable')
    if state.get('device')!='cuda' or state.get('dtype')!='torch.float16':raise RuntimeError('GPU FP16 not confirmed by owned runtime')
    response=call('/v1/chat/completions',dict(model=state['public_model'],messages=[dict(role='user',content='Say hello briefly.')],max_tokens=8,temperature=0,stream=False))
    report['response']=response
    if not response['choices'][0]['message'].get('content'):raise RuntimeError('Empty GPU response')
    if args.benchmark:
        call('/benchmark-lab/start',dict(model='optional_active',tokens=64,runs=3,quality=False))
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            job=call('/benchmark-lab')['job']
            if job['status'] not in ('running','cancelling'):break
            time.sleep(.5)
        else:
            call('/benchmark-lab/cancel',{})
            raise RuntimeError('Bounded benchmark deadline exceeded')
        report['benchmark']=job
        if job['status']!='complete':raise RuntimeError('GPU benchmark did not complete: '+str(job))
        report['benchmark_groups']=call('/benchmarks')['best_groups']
    report.update(passed=True,status='complete')
except Exception as error:
    report.update(error=str(error),status='failed')
finally:
    if started:call('/inference-backends/stop',{})
    report['finished_at']=time.time()
    report['final_backend_status']=call('/inference-backends')['status']
    (ROOT/'output/verification'/('safetensors-'+args.loader+'-gpu-bounded-real.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    folder=ROOT/'data/benchmark-checks';folder.mkdir(parents=True,exist_ok=True)
    (folder/(report['id']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in ('backend','response')},indent=2))
raise SystemExit(0 if report['passed'] else 1)
