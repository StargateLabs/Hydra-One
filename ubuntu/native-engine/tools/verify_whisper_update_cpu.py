"""Isolated official Whisper slim + exact paired CPU DLLs, real ASR and rollback."""
import base64,hashlib,json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_audio_update_cpu import call,wait

def main():
    assert call('/metrics')['live']['state']=='unloaded'
    assert call('/inference-backends')['status']=='idle'
    assert call('/local-audio')['status']=='idle'
    original=Path.home()/'.unsloth/whisper.cpp/build/bin/Release/whisper-server.exe'
    checksum=hashlib.sha256(original.read_bytes()).hexdigest()
    data=call('/updates/check',{});deadline=time.monotonic()+180
    while data['state']!='complete':
        if time.monotonic()>deadline:raise TimeoutError('Release check deadline')
        time.sleep(.5);data=call('/updates')
    release=next(row for row in data['components'] if row['id']=='whisper.cpp')
    asset=next(row for row in release['assets'] if 'windows-x64-slim' in row['name'])
    call('/updates/stage',{'component':'whisper.cpp','asset_id':asset['id']});wait({'staged'})
    prepared=call('/updates/prepare',{})
    model=ROOT.parent/'Strata-data/models/audio/whisper/ggml-tiny.bin'
    call('/updates/validate',{'model_path':str(model)});validated=wait({'validated'})
    activated=None;result=None
    try:
        activated=call('/updates/activate',{})
        result=call('/local-audio/transcribe',{'name':'validation.wav','language':'en','model':model.stem,'audio_base64':base64.b64encode((ROOT/'output/verification/audio-jfk.wav').read_bytes()).decode()})
        assert 'country' in result['text'].lower() and result['device']=='cpu'
    finally:
        call('/local-audio/stop',{})
        restored=call('/updates/rollback',{'component':'whisper.cpp'})
    assert checksum==hashlib.sha256(original.read_bytes()).hexdigest()
    report={'scope':'Official Whisper slim with isolated copies of matching GGML CPU dependencies; real ASR, no GPU or performance claim','prepared':prepared['download'],'validated':validated['download'],'activated':activated.get('whisper_runtime_selection'),'response':result,'restored':restored.get('whisper_runtime_selection'),'original_binary_sha256':checksum,'original_preserved':True,'gpu_used':False}
    (ROOT/'output/verification/whisper-update-cpu-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Whisper CPU: paired DLL isolation, real ASR, selection and rollback passed')
if __name__=='__main__':main()
