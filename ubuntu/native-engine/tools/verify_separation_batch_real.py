import sys,json,base64
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.local_separation import LocalSeparation
from serve.audio_library import AudioLibrary
from tools.verify_audio_update_cpu import call
root=Path.cwd();assert call('/inference-backends')['status']=='idle' and call('/metrics')['live']['state']=='unloaded'
engine=LocalSeparation(root);library=AudioLibrary(root);result=None;folder=root/'output/verification/htdemucs-batch-real';folder.mkdir(exist_ok=True)
try:
 result=engine.run({'audio_base64':base64.b64encode((root/'output/verification/pocket-tts-probe/sample-clone.wav').read_bytes()).decode()})
 assert len(result['stems'])==4
 for row in result['stems']:
  audio=library.read(row['artifact']['id']);(folder/(row['name']+'.wav')).write_bytes(audio)
 report=dict(passed=True,scope='Real CPU separation with complete validated WAV outputs and batch persistence; failure rollback verified separately in isolated tests',result=result,outputs=4)
finally:
 engine.stop()
 if result:
  for row in result['stems']:library.delete(row['artifact']['id'])
(root/'output/verification/htdemucs-batch-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Four complete stems saved/read back; own test artifacts exported and removed from user library')
