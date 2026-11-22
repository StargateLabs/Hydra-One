import json,time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.local_speech import LocalSpeech
root=Path.cwd();engine=LocalSpeech(root)
try:
 engine.start({});deadline=time.monotonic()+65
 while engine.status()['status']!='ready':
  state=engine.status()
  if state['status']=='error':raise RuntimeError(state['error'])
  if time.monotonic()>deadline:raise RuntimeError('Startup deadline')
  time.sleep(.2)
 (root/'output/verification/speech-voices.json').write_text(json.dumps(engine.status()['voices'],indent=2));print(json.dumps(engine.status()['voices'])[:1800],flush=True)
 result=engine.generate({'input':'Ciao, questa è una prova della voce italiana di Strata.','voice':'if_sara','language':'it','speed':1})
 import base64
 (root/'output/verification/speech-italian-cpu.wav').write_bytes(base64.b64decode(result.pop('audio_base64')));(root/'output/verification/speech-italian-cpu.json').write_text(json.dumps(result,indent=2));print(result)
finally:engine.stop()
