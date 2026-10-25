"""Bounded checks against the running local app; retains generated evidence."""
import base64,json,time,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1];base='http://127.0.0.1:8090'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));report={}
def request(path,body=None):
    req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
    with opener.open(req,timeout=150) as response:return json.load(response)
try:
    clip=root/'output/verification/audio-jfk.wav'
    result=request('/local-audio/transcribe',{'name':'verification.wav','language':'en','audio_base64':base64.b64encode(clip.read_bytes()).decode()})
    assert result.get('text');report['transcription']={k:result.get(k) for k in ('text','device','elapsed_seconds')};print('Transcription passed',flush=True)
    request('/local-audio/stop',{})
    rows=request('/local-speech/library')['items'];voice=next(r for r in rows if 'kokoro' in r.get('model','') and 1<=r.get('audio_seconds',0)<=30)
    audio=(root/'output/audio-library'/(voice['id']+'.wav')).read_bytes()
    result=request('/local-separation/run',{'audio_base64':base64.b64encode(audio).decode()});report['separation']=result;print('Separation passed',flush=True)
    result=request('/local-generative-audio/start',{'task':'voice_conversion','model':'conversion/openvoice-v2','device':'cpu','source_artifact':voice['id'],'reference_artifact':voice['id']})
    deadline=time.monotonic()+120
    while result.get('status') in ('queued','running'):
        if time.monotonic()>deadline:raise TimeoutError('Conversion verification exceeded 120 seconds')
        time.sleep(1);result=request('/local-generative-audio')
    assert result['status']=='done',result.get('error');report['voice_conversion']=result;print('Voice conversion passed',flush=True)
    for fmt in ('mp3','flac','ogg'):
        req=urllib.request.Request(base+'/local-speech/library/export',data=json.dumps({'id':voice['id'],'format':fmt}).encode(),headers={'Content-Type':'application/json','Origin':base})
        with opener.open(req,timeout=30) as response:
            data=response.read();assert len(data)>100;report['export_'+fmt]={'bytes':len(data),'type':response.headers.get_content_type()}
    assert (root/'output/audio-library'/(voice['id']+'.wav')).read_bytes()==audio
    print('Exports and original preservation passed',flush=True)
finally:
    (root/'output/verification/studio-config-live-proof.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
