import unittest
from serve.hydra_lab_app import validate_chat, LabError
class LabIsolation(unittest.TestCase):
 def test_valid(self):self.assertEqual(validate_chat({"messages":[{"role":"user","content":"Ciao"}]}),64)
 def test_invalid(self):
  for body in ({},{"messages":[]},{"messages":[{"role":"tool","content":"x"}]},{"messages":[{"role":"user","content":"x"}],"max_tokens":1000}):
   with self.subTest(body=body),self.assertRaises(LabError):validate_chat(body)
 def test_size(self):
  with self.assertRaises(LabError):validate_chat({"messages":[{"role":"user","content":"x"*17000}]})
if __name__=="__main__":unittest.main()

class StrictFlags(unittest.TestCase):
 def test_graph_rejects_numeric_boolean(self):
  with self.assertRaises(LabError):validate_chat({'messages':[{'role':'user','content':'Ciao'}],'graph':1})

class OffloadTuning(unittest.TestCase):
 def test_explicit_tuning_only(self):
  from serve.hydra_lab_app import lab_gpu_layers
  self.assertEqual(lab_gpu_layers({'gpu_layers':4}),4)
  self.assertEqual(lab_gpu_layers({'gpu_layers':29,'offload_tuning':True,'model_sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031'}),29)
  for p in ({'gpu_layers':29},{'gpu_layers':28,'offload_tuning':True},{'gpu_layers':True},{'gpu_layers':29,'offload_tuning':True,'model_sha256':'wrong'}):
   with self.subTest(p=p),self.assertRaises(LabError):lab_gpu_layers(p)


class MeasuredProfile(unittest.TestCase):
 def test_named_profile_is_explicit(self):
  from serve.hydra_lab_app import lab_gpu_layers
  self.assertEqual(lab_gpu_layers({}),0)
  p={'execution_profile':'qwen06b-gpu-full-verified-v1','offload_tuning':True,'model_sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031'}
  self.assertEqual(lab_gpu_layers(p),29)
  with self.assertRaises(LabError):lab_gpu_layers({**p,'gpu_layers':4})
 def test_effective_backend_comes_from_log(self):
  from serve.hydra_lab_app import parse_offload
  self.assertIsNone(parse_offload('requested29')['actual_layers'])
  self.assertEqual(parse_offload('I load_tensors: offloaded 29/29 layers to GPU')['actual_layers'],29)
  self.assertEqual(parse_offload('I load_tensors: offloaded 0/29 layers to GPU')['backend'],'CPU')
 def test_unavailable_is_explicit_no_fallback(self):
  from serve.hydra_lab_app import Lab
  lab=object.__new__(Lab);lab.child=None;lab.closed=True
  with self.assertRaisesRegex(RuntimeError,'provider unavailable'):lab.start()
