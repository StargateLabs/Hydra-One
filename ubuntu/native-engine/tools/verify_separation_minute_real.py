import sys,json,base64,io,wave
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.local_separation import LocalSeparation
from serve.audio_library import AudioLibrary
from tools.verify_audio_update_cpu import call
seconds=int(sys.argv[1]) if len(sys.argv)>1 else 60
assert seconds in (60,61)
label='minute' if seconds==60 else 'long-chunks'
root=Path.cwd();assert call('/inference-backends')['status']=='idle' and call('/metrics')['live']['state']=='unloaded'
engine=LocalSeparation(root);library=AudioLibrary(root);result=None;folder=root/f'output/verification/htdemucs-{label}-real';folder.mkdir(exist_ok=True)
try:
 source=root/'output/verification/pocket-tts-probe/sample-clone.wav'
 with wave.open(str(source)) as wav:
  params=wav.getparams();frames=wav.readframes(wav.getnframes());target_bytes=seconds*params.framerate*params.nchannels*params.sampwidth
 buffer=io.BytesIO()
 with wave.open(buffer,'wb') as wav:
  wav.setparams(params);wav.writeframes((frames*(target_bytes//len(frames)+1))[:target_bytes])
 result=engine.run({'audio_base64':base64.b64encode(buffer.getvalue()).decode()})
 assert abs(result['input_seconds']-seconds)<.001
 assert all(abs(row['audio_seconds']-seconds)<.25 for row in result['stems'])
 assert len(result['stems'])==4
 assert result['chunks']==(2 if seconds==61 else 1)
 for row in result['stems']:
  audio=library.read(row['artifact']['id']);(folder/(row['name']+'.wav')).write_bytes(audio)
 report=dict(passed=True,scope=f'Real {seconds}-second CPU separation on repeated local speech; four complete stems and batch persistence; not separation quality assessment',result=result,outputs=4)
finally:
 engine.stop()
 if result:
  for row in result['stems']:library.delete(row['artifact']['id'])
(root/f'output/verification/htdemucs-{label}-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Four complete stems saved/read back; own test artifacts exported and removed from user library')
