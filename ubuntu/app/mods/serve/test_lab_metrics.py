import unittest
from serve.lab_metrics import summarize
class LabMetrics(unittest.TestCase):
 def test_generation_time_keeps_scope_and_never_becomes_decode_speed(self):
  from serve.lab_metrics import measured_series
  row={'warmup':False,'generation_ms':1200,'timing_scope':'model.generate_including_prefill','output_tokens':10}
  sample=measured_series([row])[0]
  self.assertEqual(sample['generation_ms'],1200)
  self.assertEqual(sample['timing_scope'],'model.generate_including_prefill')
  self.assertIsNone(sample['decode_tok_s'])
  self.assertNotIn('generation_ms',summarize([{**row,'timing_scope':'unknown'}]))
  self.assertEqual(summarize([row])['generation_ms']['median'],1200)
 def test_unknown_decode_is_not_derived_from_wall_time(self):
  rows=[{'warmup':False,'decode_tok_s':None,'wall_s':value,'wall_tok_s':64/value} for value in (1,2,3)]
  result=summarize(rows);self.assertNotIn('decode_tok_s',result);self.assertEqual(result['wall_s']['median'],2);self.assertIsNone(result['wall_s']['p95'])
 def test_warmup_failures_and_invalid_values_never_form_records(self):
  result=summarize([{'warmup':True,'wall_s':999},{'warmup':False,'wall_s':2},{'warmup':False,'wall_s':3,'error':'failed'}])
  self.assertEqual(result['wall_s']['count'],1);self.assertEqual(result['wall_s']['median'],2)
  for value in (True,float('nan'),float('inf'),-1,0):self.assertNotIn('wall_s',summarize([{'warmup':False,'wall_s':value}]))
 def test_p95_requires_twenty_actual_samples(self):
  result=summarize([{'warmup':False,'wall_s':i} for i in range(1,21)])
  self.assertAlmostEqual(result['wall_s']['p95'],19.05);self.assertEqual(result['wall_s']['count'],20)

 def test_graph_series_keeps_unknown_decode_and_excludes_warmup(self):
  from serve.lab_metrics import measured_series
  series=measured_series([{'warmup':True,'wall_s':9,'output_tokens':99},{'warmup':False,'wall_s':2,'output_tokens':8},{'warmup':False,'wall_s':True,'output_tokens':True}])
  self.assertEqual(len(series),2);self.assertEqual(series[0]['wall_tok_s'],4);self.assertIsNone(series[0]['decode_tok_s']);self.assertIsNone(series[1]['wall_tok_s']);self.assertIsNone(series[1]['output_tokens'])
