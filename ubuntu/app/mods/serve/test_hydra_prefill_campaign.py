"""Pure v6 contracts. No model, tokenizer, process or network is executed."""
import unittest
from serve import hydra_prefill_campaign as p

class PrefillContracts(unittest.TestCase):
 def test_one_variable_candidates(self):
  self.assertEqual(p.configuration('prism-v6-control')['flags'],[])
  self.assertEqual(p.configuration('prism-v6-fa-off')['flags'],['-fa','off'])
  self.assertEqual(p.configuration('prism-v6-ub128')['flags'],['-ub','128'])
  self.assertIn('clamp',p.configuration('prism-v6-batch-only')['skip_reason'])
  with self.assertRaises(ValueError):p.configuration('prism-v6-unknown')
 def test_seven_samples_only_for_v6(self):
  from serve.hydra_lab_benchmarks import validate_runner_request
  body=dict(profile='prism-v6-control',model_id=p.MODEL_ID,prompt='x',prompt_id='v6',samples=7,max_tokens=16)
  self.assertEqual(validate_runner_request(body)['samples'],7)
  with self.assertRaises(ValueError):validate_runner_request(dict(body,model_id='local/Qwen3-0.6B-Q8_0'))
 def test_no_compute_or_ttft_is_invented(self):
  response={'content':'a','tokens_predicted':2,'timings':{'prompt_n':19,'prompt_ms':400,'prompt_per_second':47.5,'predicted_ms':300,'predicted_per_second':3.33}}
  r=p.measure(response,710,1)
  self.assertIsNone(r['prefill_compute_ms']);self.assertIsNone(r['ttft_ms']);self.assertEqual(r['prefill_ms'],400)
  self.assertEqual(r['unattributed_external_ms'],10)
 def test_terminal_only_after_every_cleanup_stage(self):
  self.assertFalse(p.can_pass(True,False,True,True))
  self.assertFalse(p.can_pass(True,True,False,True))
  self.assertTrue(p.can_pass(True,True,True,True))
 def test_v5_drift_is_not_rounded_into_a_pass(self):
  reference={'summary':{k:{'median':100} for k in ('e2e_ms','prefill_ms','decode_ms')}}
  control={'summary':{k:{'median':100 if k!='decode_ms' else 89.4847} for k in ('e2e_ms','prefill_ms','decode_ms')}}
  self.assertFalse(p.repeat_guard(reference,control)['pass'])
 def test_gate_checks_all_seven_outputs_and_three_workloads(self):
  def row(ms=100):return {'status':'PASS','cleanup':True,'actual_layers':65,'samples':[{'output':'same','prefill_ms':ms,'e2e_ms':200,'decode_ms':50} for _ in range(7)]}
  base={k:row() for k in 'ABC'};candidate={k:row(85) for k in 'ABC'}
  self.assertTrue(p.promotion_gate(base,candidate)['GO'])
  candidate['C']['samples'][6]['output']='different'
  self.assertFalse(p.promotion_gate(base,candidate)['GO'])
  candidate.pop('C');self.assertFalse(p.promotion_gate(base,candidate)['GO'])

if __name__=='__main__':unittest.main()
