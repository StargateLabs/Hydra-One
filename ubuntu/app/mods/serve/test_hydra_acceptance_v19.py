import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve import hydra_acceptance_v19 as C

class Campaign19Tests(unittest.TestCase):
 def test_warmup_consumes_last_total_slot(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.json';p.write_text(json.dumps(dict(state='ARMED',total_used=63,measured_used=63,warmup_used=0,max_total=64)))
   C.consume(p,'r',0,True)
   self.assertEqual(json.loads(p.read_text())['total_used'],64)
   with self.assertRaisesRegex(ValueError,'BUDGET'):C.consume(p,'r',1,False)
 def test_no_replay_consumption(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.json';p.write_text(json.dumps(dict(state='ARMED',total_used=0,measured_used=0,warmup_used=0,max_total=64)))
   C.consume(p,'r',1,False)
   with self.assertRaises(FileExistsError):C.consume(p,'r',1,False)
   self.assertEqual(json.loads(p.read_text())['total_used'],1)
 def test_corrupt_counter_cannot_admit_more_gpu_requests(self):
  for values in ((-1,0,0),(2,0,0),(65,65,0),(True,1,0)):
   with self.assertRaisesRegex(ValueError,'COUNTER'):C.validate_counter(dict(zip(('total_used','measured_used','warmup_used'),values),max_total=64))
 def test_quality_content_and_format_separate(self):
  self.assertTrue(C.quality('Q4','Roma')['pass'])
  q=C.quality('Q4','Roma.');self.assertTrue(q['content_correct']);self.assertFalse(q['format_correct']);self.assertFalse(q['pass'])
  self.assertFalse(C.quality('Q2','4, 5')['pass'])
  self.assertFalse(C.quality('Q1','8',True)['pass'])
  self.assertTrue(C.quality('Q6','La fonte non contiene il dato.')['pass'])
 def test_one_count_one_forward(self):
  calls=[]
  with patch.object(C,'before_request',side_effect=lambda *a:calls.append('count')):
   gate=C.RequestGate(dict(samples=1),'r',dict(warmup=False),lambda p:calls.append('native'))
   with self.assertRaisesRegex(ValueError,'PERMIT'):gate({})
   gate.authorize(1);gate({})
   with self.assertRaisesRegex(ValueError,'PERMIT'):gate({})
  self.assertEqual(calls,['count','native'])
 def test_no_v18_profile_is_admitted(self):
  self.assertFalse(C.allow_spawn(dict(profile='v8-v18-gpu-qwen'),[]))
 def test_promotion_refuses_incomplete_variable_or_slow_workload(self):
  import copy
  from serve.hydra_performance_v19 import validate_gate
  value={w:dict(protocol_complete=True,comparable=True,verdict='THROUGHPUT_PASS',ci95_gain_percent=[20,30],blocks=[dict(cpu=dict(n=7),gpu=dict(n=7))]) for w in ('short','long')}
  self.assertTrue(validate_gate(value))
  for key,bad in [('protocol_complete',False),('comparable',False),('ci95_gain_percent',[-6,30])]:
   changed=copy.deepcopy(value);changed['long'][key]=bad
   with self.assertRaises(ValueError):validate_gate(changed)
  changed=copy.deepcopy(value);changed['short']['blocks'][0]['gpu']['n']=3
  with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):validate_gate(changed)

if __name__=='__main__':unittest.main()
