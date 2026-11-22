import tempfile, unittest, json, wave
from pathlib import Path
try:
 from serve.local_generative_audio import LocalGenerativeAudio
except ImportError:
 LocalGenerativeAudio=None

class GenerativeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/"tmp");self.root=Path(self.tmp.name)/'project';self.root.mkdir()
 def tearDown(self):self.tmp.cleanup()
 def manager(self):
  self.assertIsNotNone(LocalGenerativeAudio, 'Local generative manager is missing')
  return LocalGenerativeAudio(self.root)
 def test_missing_runtime_is_reported_without_download(self):
  state=self.manager().status()
  self.assertFalse(state['runtime_installed']);self.assertEqual(state['models'],[])
 def test_requests_reject_unregistered_model_and_boolean_duration(self):
  m=self.manager()
  with self.assertRaises(ValueError):m.start({'task':'music','model':'remote/model','prompt':'piano','seconds':True})
  with self.assertRaises(ValueError):m.start({'task':'voice_conversion','model':'outside'})
 def test_model_inventory_filters_unsafe_and_wrong_formats(self):
  m=self.manager();p=m.models/'music'/'valid';p.mkdir(parents=True)
  (p/'config.json').write_text(json.dumps({'model_type':'musicgen'}));(p/'model.safetensors').write_bytes(b'x');(p/'tokenizer_config.json').write_text('{}')
  (m.models/'music'/'bad').mkdir();self.assertEqual([r['id'] for r in m.model_choices()],['music/valid'])
 def test_reference_rejects_truncation(self):
  m=self.manager();p=self.root/'a.wav'
  with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\x01\x00'*16000)
  self.assertEqual(m.reference_audio(str(p)),p)
  p.write_bytes(p.read_bytes()[:-10])
  with self.assertRaises(ValueError):m.reference_audio(str(p))
if __name__=='__main__':unittest.main()


class WorkerLifecycleTests(GenerativeTests):
 def fixture_manager(self, mode='ok'):
  import sys
  m=self.manager();m.default_python=Path(sys.executable)
  p=m.models/'music'/'fixture';p.mkdir(parents=True)
  (p/'config.json').write_text('{"model_type":"musicgen"}');(p/'model.safetensors').write_bytes(b'x');(p/'tokenizer_config.json').write_text('{}')
  script=self.root/'fixture.py'
  script.write_text("import json,sys,wave,time\nfrom pathlib import Path\nr=json.loads(Path(sys.argv[1]).read_text())\n"+("time.sleep(30)\n" if mode=='slow' else '')+"w=wave.open(r['output_path'],'wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\\x01\\x00'*16000);w.close()\nPath(r['report_path']).write_text(json.dumps({'task':r['task'],'device':r['device'],'engine':'fixture-only'}))\n")
  m._command=lambda p:[sys.executable,str(script),str(p)]
  return m
 def test_owned_worker_publishes_validated_library_artifact(self):
  import time
  m=self.fixture_manager();m.start({'task':'music','model':'music/fixture','prompt':'piano'})
  until=time.monotonic()+10
  while m.status()['status'] in ('queued','running') and time.monotonic()<until:time.sleep(.05)
  state=m.status();self.assertEqual(state['status'],'done',state)
  from serve.audio_library import AudioLibrary
  self.assertTrue(AudioLibrary(self.root).read(state['artifact']['id']).startswith(b'RIFF'));m.close()
 def test_cancel_terminates_only_owned_worker_without_artifact(self):
  import time
  m=self.fixture_manager('slow');m.start({'task':'music','model':'music/fixture','prompt':'piano'})
  until=time.monotonic()+5
  while m.child is None and time.monotonic()<until:time.sleep(.02)
  child=m.child;self.assertIsNotNone(child);m.stop();self.assertIsNotNone(child.poll());self.assertEqual(m.status()['status'],'cancelled')
  self.assertEqual(list((self.root/'output/audio-library').glob('*.wav')),[]);m.close()
