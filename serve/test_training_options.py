import hashlib
import json
from pathlib import Path
import unittest
from serve.training_options import training_options
ROOT=Path(__file__).resolve().parents[1]
class TrainingOptionsTests(unittest.TestCase):
 def test_streaming_soup_checkpoint_is_explicit(self):
  options=training_options({'runner':'soup_native','device':'cuda','layer_streaming':True,'save_steps':1,'resume_checkpoint':'checkpoint-1'})
  self.assertEqual(options['save_steps'],1)
  with self.assertRaises(ValueError):training_options({'runner':'soup_native','device':'cuda','save_steps':1})
 def test_invalid_and_unknown_fields_refused(self):
  for field,value in [('rank',True),('rank',0),('alpha',129),('learning_rate',float('nan')),('learning_rate',float('inf')),('learning_rate',0),('accumulation',33),('checkpointing','false'),('seed',-1),('unknown',1),('runner','unknown')]:
   with self.assertRaises(ValueError):training_options({field:value})
 def test_native_qlora_requires_gpu_and_accepts_checkpoint_options(self):
  self.assertEqual(training_options({'runner':'unsloth_qlora','device':'cuda'})['runner'],'unsloth_qlora')
  self.assertEqual(training_options({'runner':'unsloth_qlora','device':'cuda','save_steps':1})['save_steps'],1)
  for fields in ({'device':'cpu'},):
   with self.assertRaises(ValueError):training_options({'runner':'unsloth_qlora',**fields})
 def test_layer_streaming_is_explicit_and_soup_gpu_only(self):
  self.assertTrue(training_options({'runner':'soup_native','device':'cuda','layer_streaming':True})['layer_streaming'])
  for payload in ({'layer_streaming':'true'},{'layer_streaming':True},{'runner':'soup_native','layer_streaming':True}):
   with self.assertRaises(ValueError):training_options(payload)
 def test_custom_options_preserved(self):
  options=training_options({'rank':4,'alpha':8,'learning_rate':0.0002,'accumulation':2,'seed':9,'checkpointing':True})
  self.assertEqual(options['rank'],4);self.assertEqual(options['learning_rate'],0.0002);self.assertTrue(options['checkpointing'])
 def test_soup_runner_requires_real_minimum(self):
  with self.assertRaises(ValueError):training_options({'runner':'soup_cpu','length':32})
  self.assertEqual(training_options({'runner':'soup_cpu','length':64})['runner'],'soup_cpu')
 def test_original_soup_planner_and_license_preserved(self):
  vendor=ROOT/'serve/vendor/soup';manifest=json.loads((vendor/'manifest.json').read_text())
  self.assertEqual(manifest['revision'],'61e8c2bf354393cea85002401d0bde803b48f614')
  for name,digest in manifest['files'].items():self.assertEqual(hashlib.sha256((vendor/name).read_bytes()).hexdigest(),digest)
  self.assertIn('Apache License',(vendor/'LICENSE').read_text())
 def test_checkpoint_options_are_explicit_and_trl_only(self):
  self.assertEqual(training_options({'save_steps':2})['save_steps'],2)
  for options in ({'save_steps':True},{'save_steps':-1},{'resume_checkpoint':False},{'runner':'soup_cpu','save_steps':1}):
   with self.assertRaises(ValueError):training_options(options)
if __name__=='__main__':unittest.main()
