import unittest
from types import SimpleNamespace
from serve.hydra_system_one_bridge import execute_bridge
class IsolatedBridgeTests(unittest.TestCase):
 def test_bridge_uses_real_provider_contract_and_names_compatibility(self):
  calls=[]
  def score(body):
   calls.append(body);return dict(status='complete',alternatives=[dict(id=a['id'],tokens=[dict(logprob=-i-1)]) for i,a in enumerate(body['alternatives'])],provenance={'tokenizer':'fixture-only','model_sha256':'fixture-only'})
  lab=SimpleNamespace(prefix_score=score,profile={'model_sha256':'fixture-only','model':'fixture-only'})
  result=execute_bridge(lab,dict(state='Paris is the capital of France.',questions={'capital':dict(type='choice',instructions='What is the capital?',criteria={'Paris':'French city','London':'British city'})}))
  self.assertEqual(result['answers']['capital']['choice'],'Paris');self.assertEqual(len(calls),1)
  self.assertEqual(result['compatibility']['system_one_parity'],'NOT_VERIFIED')
 def test_pin_cache_and_unbounded_questions_are_refused(self):
  body=dict(state='x',questions={'q':dict(type='noul')})
  for patch in ({'pin_state':True},{'cache_slot':0},{'unexpected':True}):
   with self.assertRaises(ValueError):execute_bridge(None,dict(body,**patch))
