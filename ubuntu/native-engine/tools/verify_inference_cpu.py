"""Real CPU-only check of the installed GGUF gateway; no flagship speed claim."""
import json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8088'
MODEL=ROOT.parent/'Strata-data/models/optional/Qwen3-0.6B-Q8_0.gguf'
def call(path,body=None):
    request=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
def main():
    if call('/metrics')['live']['state']!='unloaded' or call('/inference-backends')['status']!='idle':
        raise RuntimeError('Both engines must be idle; no existing model is stopped')
    report=dict(scope='Actual CPU-only 0.6B gateway checks; not a 125B performance test',started_at=time.time(),passed=False)
    try:
        call('/inference-backends/start',dict(mode='gguf',model_path=str(MODEL),gpu=False,context=4096))
        deadline=time.monotonic()+90
        while True:
            state=call('/inference-backends')
            if state['status']=='ready':break
            if state['status']=='error':raise RuntimeError(state['error'])
            if time.monotonic()>deadline:raise RuntimeError('Load timeout')
            time.sleep(.5)
        model=state['public_model']
        report['state']=state
        assert state['gpu_requested'] is False and state['context_per_slot']==4096
        assert any(row['id']==model for row in call('/v1/models')['data'])
        report['props']=call('/props?model='+model)
        assert report['props']['default_generation_settings']['n_ctx']==4096
        request=urllib.request.Request(BASE+'/v1/chat/completions',data=json.dumps(dict(model=model,
            messages=[dict(role='user',content='Say hello in one short sentence.')],stream=True,max_tokens=32,
            chat_template_kwargs={'enable_thinking':False})).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=60) as response:sse=response.read().decode()
        assert 'data: [DONE]' in sse
        packets=[json.loads(line[6:]) for line in sse.splitlines() if line.startswith('data: {')]
        content=''.join(c.get('delta',{}).get('content','') or '' for p in packets for c in p.get('choices',[]))
        assert content.strip()
        report['stream']=dict(answer=content,completed=True)
        call('/benchmark-lab/start',dict(model='optional_active',tokens=128,runs=3,quality=True))
        deadline=time.monotonic()+180
        while True:
            job=call('/benchmark-lab')['job']
            if job['status'] not in ('running','cancelling'):break
            if time.monotonic()>deadline:raise RuntimeError('Benchmark timeout')
            time.sleep(1)
        report['benchmark']=job
        assert job['status']=='complete',job.get('error')
        assert len(job['results'][0]['series'])==4
        assert job['results'][0]['summary']['wall_tok_s']['median']>0
        report['passed']=True
    finally:
        state=call('/inference-backends')
        if state.get('model_path')==str(MODEL) and not state.get('busy'):call('/inference-backends/stop',{})
        report['finished_at']=time.time()
        (ROOT/'output/verification/inference-cpu-integrated-20261010.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],scope=report['scope'],benchmark=report['benchmark']['status'])))
if __name__=='__main__':main()
