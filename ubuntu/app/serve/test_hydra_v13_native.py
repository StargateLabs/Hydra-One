"""Contracts for bounded native CPU generation, distinct from model execution."""
import unittest
from serve import hydra_lab_native_tasks as native
from serve.hydra_lab_benchmarks import validate_runner_request
from serve.test_hydra_feature_control import FeatureControlTests

class NativeGenerationTests(unittest.TestCase):
 def test_requested_budget_reaches_cli(self):
  args=native.text_arguments('model.gguf',dict(prompt='Rispondi in italiano.',max_tokens=96))
  self.assertEqual(args[args.index('-n')+1],'96')
  self.assertIn('--no-conversation',args)
 def test_explicit_reasoning_requires_capability(self):
  body=dict(prompt='Ciao',max_tokens=96,thinking='off')
  with self.assertRaisesRegex(ValueError,'THINKING_CAPABILITY'):native.text_arguments('model',body)
  args=native.text_arguments('model',body,capabilities={'reasoning','thinking_template'})
  self.assertEqual(args[args.index('--reasoning')+1],'off')
  self.assertNotIn('--no-conversation',args)
  self.assertEqual(args[args.index('--chat-template-kwargs')+1],'{"enable_thinking":false}')
  self.assertEqual(args[args.index('--reasoning-budget')+1],'0')
 def test_bad_thinking_and_budget_rejected(self):
  for value in ('yes',False,None):
   with self.assertRaises(ValueError):native.text_arguments('model',dict(prompt='x',max_tokens=32,thinking=value))
  for value in (0,129,True):
   with self.assertRaises(ValueError):native.text_arguments('model',dict(prompt='x',max_tokens=value))
 def test_request_thinking_is_native_text_only(self):
  base=dict(profile='cpu',model_id='prism-ml/Ternary-Bonsai-2-27B-gguf',prompt='Ciao',prompt_id='v13',max_tokens=96,samples=1,thinking='off')
  self.assertEqual(validate_runner_request(base)['thinking'],'off')
  with self.assertRaises(ValueError):validate_runner_request(dict(base,model_id='audio-cpp/audio.cpp-gguf'))

class CompletePresetTests(FeatureControlTests):
 def test_complete_cpu_resolves_graph_and_score_without_gpu(self):
  plan=self.control.preset('hydra-local-complete-v1')
  self.assertEqual(plan['preset_id'],'hydra-local-complete-v1')
  self.assertFalse(plan['blocked'])
  self.change(plan['changes'])
  for path in ('/lab/chat','/lab/retrieve','/lab/score'):
   self.control.resolve(dict(path=path,request=dict(graph=True,variant='H1v2')))
  self.assertFalse(any(value['desired'] for key,value in self.control.export()['features'].items() if key.startswith('runtime.')))
