"""V7 contracts; model generation belongs to the separate real campaign."""
import unittest
from serve import hydra_v7_experiments as v

class V7Contracts(unittest.TestCase):
 def test_options_are_bounded_and_single_variable(self):
  self.assertEqual(v.options('v7-qwen-control'),[])
  self.assertEqual(v.options('v7-qwen-cache'),['--cache-prompt'])
  self.assertEqual(v.options('v7-qwen-nommap'),['--no-mmap'])
  with self.assertRaises(ValueError):v.options('v7-unknown')
 def test_admission_is_specific(self):
  from serve.hydra_lab_benchmarks import validate_runner_request
  b=dict(profile='v7-qwen-control',model_id='local/Qwen3-0.6B-Q8_0',prompt='x',prompt_id='v7',samples=7,max_tokens=16)
  self.assertEqual(validate_runner_request(b)['samples'],7)
  with self.assertRaises(ValueError):validate_runner_request(dict(b,model_id='unsloth/Z-Image-Turbo-GGUF'))
 def test_prompt_cache_changes_only_request(self):
  a=v.request('x',False);b=v.request('x',True);self.assertEqual({k:x for k,x in a.items() if k!='cache_prompt'},{k:x for k,x in b.items() if k!='cache_prompt'})
 def test_promotion_uses_all_outputs(self):
  base={'samples':[{'output':'a','e2e_ms':100}]*7};cand={'samples':[{'output':'a','e2e_ms':80}]*7}
  self.assertTrue(v.compare(base,cand)['GO']);cand['samples'][-1]={'output':'b','e2e_ms':80};self.assertFalse(v.compare(base,cand)['GO'])

class TerminalPublication(unittest.TestCase):
 def test_native_runners_publish_pass_only_after_resource_release(self):
  from pathlib import Path
  for name in ('hydra_lab_native_tasks.py','hydra_lab_audio_adapter.py','hydra_lab_benchmarks.py'):
   source=(Path(__file__).parent/name).read_text()
   with self.subTest(adapter=name):
    release=source.rfind('release_runtime_lock(lease)')
    success=source.rfind("row['status']='PASS'")
    self.assertGreater(success,release,'terminal PASS is visible while resources are owned')
    self.assertIn("row['cleanup']",source[release:source.find("\n",success)])

if __name__=='__main__':unittest.main()
