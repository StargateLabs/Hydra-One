import tempfile,unittest,wave
from pathlib import Path
from serve.audiocraft_native import validate_options

class NativeConditioningTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.audio=Path(self.tmp.name)/'source.wav'
  with wave.open(str(self.audio),'wb') as f:f.setparams((1,2,16000,0,'NONE',''));f.writeframes(b'\1\0'*48000)
 def reference(self,value,minimum_seconds=1):return self.audio
 def test_style_excerpt_must_fit_reference_and_native_range(self):
  result=validate_options('style',dict(source_path=str(self.audio),style_excerpt=3,seconds=4),self.reference)
  self.assertEqual(result['style_excerpt'],3);self.assertEqual(result['source_path'],str(self.audio))
  for value in (1,4.5,float('nan')):
   with self.assertRaises(ValueError):validate_options('style',dict(style_excerpt=value,seconds=4),self.reference)
 def test_jasco_chords_must_be_ordered_and_inside_ten_seconds(self):
  result=validate_options('jasco',dict(prompt='piano',chords=[['C',0],['G',5]]),self.reference)
  self.assertEqual(result['seconds'],10);self.assertEqual(result['chords'],[['C',0],['G',5]])
  for chords in ([['C',5],['G',0]],[['C',10]],[['C',float('nan')]],'C at zero'):
   with self.assertRaises(ValueError):validate_options('jasco',dict(prompt='piano',chords=chords),self.reference)
 def test_native_solver_options_reject_coercion(self):
  with self.assertRaises(ValueError):validate_options('jasco',dict(prompt='piano',jasco_euler='yes'),self.reference)
