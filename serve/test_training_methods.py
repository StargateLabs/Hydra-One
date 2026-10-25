import json,tempfile,unittest
from pathlib import Path
from serve.training_options import training_options
from tools.train_local_lora import dataset_rows
class Methods(unittest.TestCase):
 def test_methods_require_trl_and_reject_layer_streaming(self):
  self.assertEqual(training_options({'method':'dpo'})['method'],'dpo')
  for payload in ({'method':'unknown'},{'method':'grpo','runner':'soup_native'},{'method':'dpo','layer_streaming':True},{'method':'dpo','device':'cuda'}):
   with self.assertRaises(ValueError):training_options(payload)
 def test_advanced_checkpoint_save_and_resume_are_accepted(self):
  for payload in ({'save_steps':1},{'resume_checkpoint':'output/training/run/trainer/checkpoint-1'}):
   with self.subTest(payload=payload):
    self.assertTrue(training_options({'method':'dpo',**payload}))
 def test_preferences_require_distinct_nonempty_answers(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'data.jsonl'
   path.write_text(json.dumps({'prompt':'Hello','chosen':'Hi','rejected':'No'})+'\n')
   self.assertEqual(dataset_rows(path,method='dpo')[0]['chosen'],'Hi')
   path.write_text(json.dumps({'prompt':'Hello','chosen':'Hi','rejected':'Hi'})+'\n')
   with self.assertRaises(ValueError):dataset_rows(path,method='dpo')
 def test_grpo_requires_an_explicit_target(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'data.jsonl';path.write_text(json.dumps({'prompt':'Say hi','target':'Hi'})+'\n')
   self.assertEqual(dataset_rows(path,method='grpo')[0]['target'],'Hi')

class RewardDatasetTests(unittest.TestCase):
 def test_reward_reuses_preferences_but_rejects_invalid_pairs(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'preferences.jsonl';path.write_text(json.dumps({'prompt':'Hello','chosen':'Hi','rejected':'No'}),encoding='utf-8')
   self.assertEqual(dataset_rows(path,method='reward')[0]['chosen'],'Hi')
   self.assertEqual(training_options({'method':'reward'})['method'],'reward')
   with self.assertRaises(ValueError):training_options({'method':'reward','device':'cuda'})
