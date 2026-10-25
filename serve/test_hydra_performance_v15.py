import unittest
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock
from serve import test_hydra_feature_control as fixtures
from serve.hydra_feature_control import runtime_options
from serve.hydra_performance_v15 import validate
class CandidateModes(unittest.TestCase):
 setUp=fixtures.FeatureControlTests.setUp
 tearDown=fixtures.FeatureControlTests.tearDown
 change=fixtures.FeatureControlTests.change
 def test_standard_candidate_is_explicit_and_off_restores_reference(self):
  self.change({'V7-E-028':{'desired':False},'V7-E-029':{'desired':True,'parameters':{'loader_mode':1}},'adapter.local/Qwen3-0.6B-Q8_0':{'desired':True}},allow_blocked=True)
  self.assertEqual(runtime_options(self.control)['model_io'],'candidate-standard')
  self.control.resolve({'path':'/lab/performance','request':{'workload':'short','transport':'runner','repetitions':1}})
  self.change({'V7-E-029':{'desired':False}},allow_blocked=True)
  self.assertEqual(runtime_options(self.control)['model_io'],'standard')
class ProtocolTests(unittest.TestCase):
 def test_gpu_profile_refused_before_backend_start(self):
  from serve.hydra_performance_v15 import execute
  lab=SimpleNamespace(profile={'model_sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031','gpu_layers':4,'offload_tuning':True},start=Mock())
  with self.assertRaisesRegex(ValueError,'GPU_QUARANTINED'):execute(lab,{'workload':'short','transport':'runner','repetitions':1})
  lab.start.assert_not_called()
 def test_incomplete_scoring_cannot_be_performance_success(self):
  from serve.hydra_performance_v15 import require_complete
  with self.assertRaisesRegex(RuntimeError,'PERFORMANCE_INCOMPLETE'):require_complete({'status':'error','scoring':{'status':'error'}})
 def test_direct_baseline_retains_existing_guarded_client(self):
  from serve.hydra_lab_app import Lab
  lab=Lab.__new__(Lab);lab.features=None;lab.graph_options={};lab.start=lambda:None;lab.model_id='optional-model';lab.profile={'model':'fixture'};lab.startup_ms=1;lab.identity_verification_ms=1;lab.calls=[]
  packet={'id':'fixture','created':0,'model':'optional-model','choices':[{'delta':{'content':'ok'},'finish_reason':'length'}],'usage':{'completion_tokens':16},'timings':{'cache_n':0}}
  lab.client=SimpleNamespace(chat=Mock(return_value=iter([packet])),graph=None,guards={})
  value=lab.chat({'messages':[{'role':'user','content':'fixture'}],'max_tokens':16},_performance=True,_transport='direct')
  self.assertEqual(value['response']['usage']['completion_tokens'],16)
  self.assertTrue(lab.client.chat.call_args.kwargs['stream'])
 def test_frozen_limits_and_thresholds(self):
  value=validate({'workload':'short','transport':'runner','repetitions':1})
  self.assertEqual([value['workloads'][k]['max_tokens'] for k in ('short','medium')],[16,64])
  self.assertEqual(value['thresholds']['minimum_samples'],15)
  self.assertEqual(value['thresholds']['minimum_e2e_gain_percent'],15)
 def test_unbounded_options_refused_before_execution(self):
  for body in ({'workload':'arbitrary','transport':'runner','repetitions':1},{'workload':'short','transport':'runner','repetitions':True},{'workload':'short','transport':'runner','repetitions':16},{'workload':'short','transport':'runner','repetitions':1,'prompt':'bypass'}):
   with self.assertRaises(ValueError):validate(body)
 def test_protocol_tamper_refused(self):
  with patch('serve.hydra_performance_v15.PROTOCOL') as source:
   source.read_bytes.return_value=b'{}'
   with self.assertRaisesRegex(ValueError,'identity'):validate({'workload':'short','transport':'runner','repetitions':1})
if __name__=='__main__':unittest.main()
