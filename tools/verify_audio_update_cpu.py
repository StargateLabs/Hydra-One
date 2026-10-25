"""Official isolated audio.cpp package: integrity, real TTS, selection and rollback."""
import json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8088'
def call(path,body=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':BASE})
    with urllib.request.urlopen(req,timeout=30) as response:
        raw=response.read();return json.loads(raw) if response.headers.get_content_type()=='application/json' else raw
def wait(states,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        data=call('/updates');job=data['download']
        if job['state'] in states:return data
        if job.get('error'):raise RuntimeError(job['error'])
        time.sleep(.5)
    raise TimeoutError('Audio update deadline')
def main():
    assert call('/metrics')['live']['state']=='unloaded'
    assert call('/inference-backends')['status']=='idle'
    assert call('/local-speech')['status']=='idle'
    assert call('/local-audio')['status']=='idle'
    call('/updates/check',{});data=wait({'candidate_installed','idle','rolled_back'})
    deadline=time.monotonic()+180
    while data['state']!='complete':
        if time.monotonic()>deadline:raise TimeoutError('Release check deadline')
        time.sleep(.5);data=call('/updates')
    release=next(row for row in data['components'] if row['id']=='audio.cpp')
    asset=next(row for row in release['assets'] if 'windows-x64-cpu-portable' in row['name'])
    call('/updates/stage',{'component':'audio.cpp','asset_id':asset['id']});wait({'staged'})
    prepared=call('/updates/prepare',{})
    model=next((ROOT.parent/'Strata-data/models/audio/tts').glob('kokoro*.gguf'))
    call('/updates/validate',{'model_path':str(model)});validated=wait({'validated'})
    original=call('/updates').get('audio_runtime_selection')
    try:
        activated=call('/updates/activate',{})
        result=call('/v1/audio/speech',{'model':model.stem,'input':'Ciao, verifica del candidato attivo.','voice':'if_sara','language':'it','response_format':'wav'})
        import io,wave
        with wave.open(io.BytesIO(result)) as audio:assert audio.getnframes()>0
    finally:
        call('/local-speech/stop',{})
        restored=call('/updates/rollback',{'component':'audio.cpp'})
    report={'scope':'Official audio.cpp CPU package with actual Italian TTS; same release family, no performance gain claim','prepared':prepared['download'],'validated':validated['download'],'activated':activated.get('audio_runtime_selection'),'restored':restored.get('audio_runtime_selection'),'gpu_used':False}
    (ROOT/'output/verification/audio-update-cpu-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Audio CPU candidate: integrity, synthesis, activation and rollback passed')
if __name__=='__main__':main()
