"""One real local speech request, saving WAV and measured evidence."""
import argparse
import base64
import io
import json
from pathlib import Path
import struct
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.voicestudio import VoiceStudio


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesize',action='store_true',required=True)
    args=parser.parse_args()
    client=VoiceStudio(ROOT);state=client.status()
    if not state['connected']:raise RuntimeError(state['message'])
    text='VoiceStudio is connected to Strata. This audio was generated locally.'
    started=time.monotonic();result=client.speech({'input':text,'voice':'default','language':'en'});elapsed=time.monotonic()-started
    raw=base64.b64decode(result['audio_base64'])
    state=client.status()
    with wave.open(io.BytesIO(raw),'rb') as audio:
        frames=audio.readframes(audio.getnframes())
        evidence={'text':text,'version':state['version'],'device':state.get('active_engine_device') or state['device'],'pytorch_device':state['device'],'active_engine':state.get('active_engine'),'gpu_name':state.get('active_engine_gpu_name'),'duration_s':audio.getnframes()/audio.getframerate(),'sample_rate':audio.getframerate(),'channels':audio.getnchannels(),'sample_width':audio.getsampwidth(),'audio_bytes':len(raw),'generation_elapsed_s':round(elapsed,3),'nonzero_samples':any(frames),'source':'actual VoiceStudio local backend /v1/audio/speech','listening_verified':False}
    if not evidence['duration_s'] or not evidence['nonzero_samples']:raise RuntimeError('Generated audio is empty or silent.')
    target=ROOT/'output/voicestudio';target.mkdir(parents=True,exist_ok=True)
    (target/'verification.wav').write_bytes(raw)
    (target/'verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':main()
