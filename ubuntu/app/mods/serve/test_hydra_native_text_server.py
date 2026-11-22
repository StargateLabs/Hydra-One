import unittest
from serve.hydra_native_text_server import server_request,server_arguments
class NativeTextServerTests(unittest.TestCase):
 def test_routed_only_inside_admitted_execute(self):
  from unittest.mock import patch
  from serve.hydra_lab_benchmarks import Workspace
  body=dict(profile='cpu',model_id='prism-ml/Ternary-Bonsai-2-27B-gguf',prompt='Ciao',prompt_id='server-contract',max_tokens=32,samples=1,thinking='off')
  workspace=object()
  with patch('serve.hydra_native_text_server.execute',return_value={'status':'PASS'}) as execute:
   self.assertEqual(Workspace.execute.__wrapped__(workspace,body,_key='owned'),{'status':'PASS'})
   self.assertEqual(execute.call_args.args[2],'owned')
 def test_thinking_is_explicit_template_parameter(self):
  body=dict(prompt='Ciao',max_tokens=96,thinking='off')
  request=server_request(body)
  self.assertFalse(request['chat_template_kwargs']['enable_thinking'])
  self.assertEqual(request['max_tokens'],96)
  self.assertFalse(request['cache_prompt'])
  self.assertFalse(request['stream'])
 def test_cpu_arguments_and_single_slot(self):
  args=server_arguments('server.exe','model.gguf',12345)
  self.assertEqual(args[args.index('-ngl')+1],'0')
  self.assertEqual(args[args.index('--parallel')+1],'1')
 def test_invalid_explicit_options_refused(self):
  for thinking in ('auto','yes',False):
   with self.assertRaises(ValueError):server_request(dict(prompt='x',max_tokens=32,thinking=thinking))
