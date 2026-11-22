"""Pure campaign contracts; no native model is executed by these tests."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from serve import hydra_prism_campaign as p

class PrismCampaignTests(unittest.TestCase):
 def test_profiles_are_bounded_and_specific(self):
  self.assertEqual(p.profile_spec('prism-v5-cpu-2'),('CPU',2,0))
  self.assertEqual(p.profile_spec('prism-v5-vulkan-2'),('Vulkan',2,99))
  for n in (4,8,16):self.assertEqual(p.profile_spec('prism-v5-cpu-'+str(n)),('CPU',n,0))
  with self.assertRaises(ValueError):p.profile_spec('prism-v5-cpu-32')
 def test_runner_rejects_profile_on_other_models(self):
  from serve.hydra_lab_benchmarks import validate_runner_request
  body=dict(profile='prism-v5-vulkan-2',model_id=p.MODEL_ID,prompt='x',prompt_id='x',samples=3,max_tokens=16)
  self.assertEqual(validate_runner_request(body)['profile'],body['profile'])
  with self.assertRaises(ValueError):validate_runner_request(dict(body,model_id='local/Qwen3-0.6B-Q8_0'))
 def test_native_response_is_not_inferred(self):
  x=p.measured_response({'content':' x ','tokens_predicted':2,'timings':{'prompt_ms':12,'prompt_n':4,'prompt_per_second':333,'predicted_ms':30,'predicted_n':2,'predicted_per_second':66.6}},50)
  self.assertEqual(x['output'],' x ');self.assertEqual(x['tokens'],2);self.assertEqual(x['decode_tps'],66.6);self.assertIsNone(x['ttft_ms'])
  with self.assertRaises(ValueError):p.measured_response({'content':'x'},2)
 def test_backend_evidence_is_required(self):
  text='ggml_vulkan: 0 = AMD Radeon RX 7900 XTX\nload_tensors: offloaded 65/65 layers to GPU\nload_tensors: Vulkan0 model buffer size = 6000.00 MiB\nllama_context: Vulkan0 compute buffer size = 60.00 MiB'
  self.assertEqual(p.backend_evidence(text,'Vulkan')['actual_layers'],65)
  with self.assertRaises(ValueError):p.backend_evidence('requested Vulkan', 'Vulkan')
  with self.assertRaises(ValueError):p.backend_evidence('model loaded; buffers hidden','CPU')
 def test_request_uses_raw_exact_bytes_without_cache(self):
  r=p.completion_request(' x\n',16)
  self.assertEqual(r['prompt'],' x\n');self.assertFalse(r['cache_prompt']);self.assertEqual(r['temperature'],0);self.assertEqual(r['seed'],42);self.assertEqual(r['n_predict'],16)
 def test_quality_gate_checks_every_sample(self):
  a={'samples':[{'output':'a'}]*3,'status':'PASS','cleanup':True}
  b={'samples':[{'output':'a'}]*2+[{'output':'b'}],'status':'PASS','cleanup':True}
  self.assertEqual(p.output_gate(a,a),'TEXT_IDENTICAL')
  self.assertEqual(p.output_gate(a,b),'QUALITY_GATE_FAILED')
 def test_terminal_success_requires_cleanup(self):
  self.assertEqual(p.terminal_status(True,True,'RUNNING'),'PASS')
  self.assertEqual(p.terminal_status(True,False,'RUNNING'),'FAIL')
  self.assertEqual(p.terminal_status(False,True,'CANCELLED'),'CANCELLED')
  self.assertEqual(p.terminal_status(True,True,'FAIL'),'FAIL')
 def test_verified_profile_needs_real_registry_proof(self):
  self.assertEqual(p.profile_spec('prism-bonsai27b-vulkan-verified-v1'),('Vulkan',2,99))
  cfg={'model_hash':'model','runtimes':{'Vulkan':{'files':{'llama-server.exe':'runtime'}}}}
  proof={'status':'PASS','cleanup':True,'model_hash':'model','runtime_hash':'runtime','backend':'Vulkan','actual_layers':65,'quality_gate':'TEXT_IDENTICAL','samples':[{}]*3,'controlled_comparison':{'improvement_percent':99}}
  self.assertTrue(p.verified_profile_allowed(cfg,proof))
  self.assertFalse(p.verified_profile_allowed(cfg,dict(proof,status='CANCELLED')))
  self.assertFalse(p.verified_profile_allowed(cfg,dict(proof,cleanup=False)))
  self.assertFalse(p.verified_profile_allowed(cfg,dict(proof,quality_gate='QUALITY_GATE_FAILED')))
 def test_disabled_campaign_starts_nothing(self):
  workspace=SimpleNamespace(lab=SimpleNamespace(profile={}))
  with patch.dict('os.environ',{'HYDRA_LAB_MODE':'0'}),patch.object(p.subprocess,'Popen') as launch:
   with self.assertRaises(ValueError):p.execute(workspace,{'profile':'prism-v5-vulkan-2'})
   launch.assert_not_called()

if __name__=='__main__':unittest.main()
