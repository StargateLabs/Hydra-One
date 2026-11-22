"""Verify the recommended context reaches the owned CPU runtime on a trained local model."""
import json,time,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def call(path,body=None):
    request=urllib.request.Request('http://127.0.0.1:8088'+path,
        data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)

def main():
    model=json.loads((ROOT/'output/verification/safetensors-trained-model-download.json').read_text())['path']
    if call('/metrics')['live']['state']!='unloaded' or call('/inference-backends')['status']!='idle':
        raise RuntimeError('Existing engines must be idle')
    payload=dict(mode='safetensors',model_path=model,gpu=False,fit_mode='auto',fit_goal='context')
    fitted=call('/inference-backends/fit',payload)
    target=fitted['recommended']['context']
    report=dict(scope='Real trained local model, CPU only; functional fit verification, not 125B performance.',model_path=model,target_context=target)
    try:
        call('/inference-backends/start',payload)
        deadline=time.monotonic()+90
        while True:
            state=call('/inference-backends')
            if state['status']=='ready':break
            if state['status']=='error':raise RuntimeError(state['error'])
            if time.monotonic()>deadline:raise RuntimeError('CPU readiness timeout')
            time.sleep(.5)
        assert state['context']==target and state['context_source']=='owned_python_runtime'
        assert state['gpu_requested'] is False
        response=call('/v1/chat/completions',dict(model=state['public_model'],messages=[dict(role='user',content='Say hello.')],max_tokens=16,temperature=0))
        assert response['choices'][0]['message']['content'].strip()
        report.update(passed=True,confirmed_context=state['context'],response=response)
    finally:
        state=call('/inference-backends')
        if state.get('model_path')==model and not state.get('busy'):call('/inference-backends/stop',{})
    report['finished_at']=time.time()
    (ROOT/'output/verification/native-fit-cpu-real-20261010.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,device='CPU',configured_context=target)))

if __name__=='__main__':main()
