"""Real small-model lifecycle and API smoke check; not a flagship benchmark."""
import json
from pathlib import Path
import time
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8088'

def call(path,body=None):
    request=Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=60) as response:return json.load(response)

def wait_ready():
    deadline=time.monotonic()+190
    while time.monotonic()<deadline:
        state=call('/inference-backends')
        if state['status']=='ready':return state
        if state['status']=='error':raise RuntimeError(state['error'])
        time.sleep(.5)
    raise RuntimeError('Backend readiness timeout')

if __name__=='__main__':
    started_at=time.time()
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,default=ROOT.parent/'Strata-data/models/optional/Qwen3-0.6B-Q8_0.gguf')
    parser.add_argument('--output',type=Path,default=ROOT/'output/verification/optional-real-20261010.json')
    parser.add_argument('--cpu-only',action='store_true',help='Verify lifecycle without GPU model inference')
    args=parser.parse_args()
    if call('/inference-backends')['status']!='idle':raise RuntimeError('Optional backend already active')
    rows=[]
    for gpu in ((False,) if args.cpu_only else (False,True)):
        try:
            call('/inference-backends/start',{'mode':'gguf','model_path':str(args.model.resolve()),'gpu':gpu})
            state=wait_ready();model=state['public_model']
            assert state['owned_process'] and (ROOT/'data/.gpu-campaign.lock').exists()
            models=call('/v1/models')['data'];assert any(row['id']==model for row in models)
            started=time.monotonic()
            response=call('/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':'Return only the number: 7 + 5 = ?'}],'chat_template_kwargs':{'enable_thinking':False},'max_tokens':128,'temperature':0,'stream':False})
            answer=response['choices'][0]['message']['content']
            if not answer:raise RuntimeError('No final text; inspect reasoning and finish_reason')
            rows.append({'gpu_requested':gpu,'public_model':model,'answer':answer,'arithmetic_check':{'expected':'12','passed':'12' in answer},'usage':response.get('usage'),'timings':response.get('timings'),'wall_s':time.monotonic()-started})
        finally:
            call('/inference-backends/stop',{})
        assert not (ROOT/'data/.gpu-campaign.lock').exists()
        assert call('/inference-backends')['status']=='idle'
    report={'status':'complete','model_file':str(args.model.resolve()),'scope':'Actual selected GGUF '+('CPU-only' if args.cpu_only else 'CPU/GPU')+' smoke checks; not a 125B benchmark','runs':rows,'operational_state':call('/metrics')['live']['state']}
    report.update(kind='backend_check',id=time.strftime('%Y%m%d-%H%M%S',time.gmtime(started_at))+'-optional-'+str(int(started_at*1000)%100000),started_at=started_at,finished_at=time.time())
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    directory=ROOT/'data/benchmark-checks';directory.mkdir(parents=True,exist_ok=True)
    (directory/(report['id']+'.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
