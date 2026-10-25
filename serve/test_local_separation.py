import base64,io,tempfile,unittest,wave
from serve.local_separation import LocalSeparation
class SeparationTests(unittest.TestCase):
  def test_invalid_inputs_never_start_worker(self):
   with tempfile.TemporaryDirectory() as root:
    engine=LocalSeparation(root)
    for value in (None,'!',True,'A'* (16*1024**2+1)):
     with self.assertRaises((ValueError,TypeError)):engine.run({'audio_base64':value})
     self.assertIsNone(engine.child)
  def test_long_audio_is_rejected_before_loading(self):
   out=io.BytesIO()
   with wave.open(out,'wb') as audio:audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\0\0'*1448000)
   with tempfile.TemporaryDirectory() as root:
    engine=LocalSeparation(root)
    with self.assertRaisesRegex(ValueError,'180 seconds'):engine.run({'audio_base64':base64.b64encode(out.getvalue()).decode()})
    self.assertIsNone(engine.child);self.assertFalse(engine.lock.locked())

  def test_corrupt_or_mismatched_output_is_not_a_completed_stem(self):
   from serve.local_separation import stem_seconds
   out=io.BytesIO()
   with wave.open(out,'wb') as wav:wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(44100);wav.writeframes(b'\0'*17640)
   data=out.getvalue();self.assertAlmostEqual(stem_seconds(data,.1),.1)
   with self.assertRaisesRegex(ValueError,'Truncated'):stem_seconds(data[:-8],.1)
   with self.assertRaisesRegex(ValueError,'duration'):stem_seconds(data,1)

  def test_chunk_split_and_rejoin_preserves_samples(self):
   from pathlib import Path
   from serve.local_separation import split_audio,combine_stems
   raw=b'\x01\x00\x02\x00'*(44100*61)
   with tempfile.TemporaryDirectory() as folder:
    source=Path(folder)/'input.wav'
    with wave.open(str(source),'wb') as writer:writer.setnchannels(2);writer.setsampwidth(2);writer.setframerate(44100);writer.writeframes(raw)
    chunks=split_audio(source,folder)
    self.assertEqual([seconds for _,seconds in chunks],[60,1])
    result=combine_stems([(path.read_bytes(),seconds) for path,seconds in chunks],61)
    with wave.open(io.BytesIO(result)) as reader:self.assertEqual(reader.readframes(reader.getnframes()),raw)

  def test_stem_ids_follow_the_model_variant_instead_of_a_fixed_count(self):
   from serve.local_separation import stem_ids
   self.assertEqual(stem_ids([{'id':'vocals'},{'id':'drums'},{'id':'bass'},{'id':'other'}]),['vocals','drums','bass','other'])
   self.assertEqual(stem_ids([{'id':'vocals'},{'id':'drums'},{'id':'bass'},{'id':'other'},{'id':'piano'},{'id':'guitar'}]),['vocals','drums','bass','other','piano','guitar'])
   for outputs in ([],[{}],[{'id':''},{'id':'drums'}],[{'id':'vocals'},{'id':'vocals'}],[{'id':1},{'id':'drums'}],'not-a-list'):
    with self.subTest(outputs=outputs),self.assertRaisesRegex(ValueError,'stem'):stem_ids(outputs)
