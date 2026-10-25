import tempfile,unittest,json,io,wave,struct
from pathlib import Path
from serve.audio_library import AudioLibrary
from serve import audiocraft_training as training
class TrainingDataset(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def audio(self,value):
  stream=io.BytesIO()
  with wave.open(stream,'wb') as w:w.setparams((1,2,8000,0,'NONE','not compressed'));w.writeframes(struct.pack('<h',value)*16000)
  return AudioLibrary(self.root).save(stream.getvalue(),{})['id']
 def test_native_manifests_split_without_overlap_and_keep_sources(self):
  ids=[self.audio(100),self.audio(200)]
  result=training.prepare_dataset(self.root,{'items':[{'id':i,'description':'A synthetic tone.'} for i in ids]})
  row=json.loads(Path(result['dataset']).read_text());self.assertEqual(row['train_rows'],1);self.assertEqual(row['validation_rows'],1)
  self.assertTrue(all((self.root/'output/audio-library'/(i+'.wav')).is_file() for i in ids))
  self.assertTrue((Path(result['dataset']).parent/'train/data.jsonl').is_file())
 def test_duplicate_audio_cannot_leak_into_validation(self):
  identity=self.audio(100)
  with self.assertRaises(ValueError):training.prepare_dataset(self.root,{'items':[{'id':identity,'description':'x'},{'id':identity,'description':'y'}]})
 def test_unowned_dataset_refused(self):
  with self.assertRaises(ValueError):training.dataset(self.root,str(self.root/'foreign.json'))
