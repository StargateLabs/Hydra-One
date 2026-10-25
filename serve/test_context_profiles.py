import unittest
from serve.context_profiles import plan

class ContextTests(unittest.TestCase):
 def test_memory_breakdown_distinguishes_gpu_estimate_ram_bound_and_reserve(self):
  cpu=plan(self.meta,2**30,64*2**30)
  row=cpu['options'][0]
  self.assertEqual(row['gpu_estimated_alloc_gib'],0)
  self.assertAlmostEqual(row['ram_required_gib']-row['ram_estimated_upper_gib'],8)
  gpu=plan(self.meta,2**30,64*2**30,24*2**30,gpu_total=24*2**30)
  row=gpu['options'][0]
  self.assertAlmostEqual(row['gpu_estimated_alloc_gib'],gpu['weights_gib']+row['kv_gib']+row['compute_buffers_gib'])
  self.assertLess(row['gpu_estimated_alloc_gib'],row['gpu_required_gib'])
 def setUp(self):
  self.meta={'general.architecture':'spark2_5','spark2_5.context_length':1048576,'spark2_5.block_count':36,
             'spark2_5.attention.head_count_kv':4,'spark2_5.attention.key_length':256,'spark2_5.attention.value_length':256}
 def test_model_limit_distinct_from_recommendation(self):
  result=plan(self.meta,8*2**30,48*2**30,23*2**30)
  self.assertEqual(result['model_max_context'],1048576);self.assertEqual(result['recommended_context'],max(row['context'] for row in result['options'] if row['fits']))
  row=next(r for r in result['options'] if r['context']==1048576);self.assertFalse(row['fits'])
 def test_less_memory_reduces_context(self):
  result=plan(self.meta,8*2**30,48*2**30,14*2**30)
  row=next(r for r in result['options'] if r['context']==32768)
  self.assertFalse(row['full_gpu']);self.assertTrue(row['mixed_cpu_gpu'])
 def test_unknown_layout_cannot_expand(self):
  result=plan({'general.architecture':'unknown'},2**30,32*2**30)
  self.assertEqual([r['context'] for r in result['options']],[1024,2048,4096]);self.assertIsNone(result['kv_bytes_per_token'])
 def test_no_fit_is_not_recommended(self):
  self.assertIsNone(plan(self.meta,8*2**30,10*2**30,12*2**30)['recommended_context'])
 def test_declared_limit_is_enforced(self):
  result=plan({**self.meta,'spark2_5.context_length':8192},2**30,64*2**30,24*2**30)
  self.assertEqual(result['recommended_context'],8192)
class SlidingWindowTests(unittest.TestCase):
 def test_spark_pattern_is_priced_without_artificial_64k_limit(self):
  metadata={'general.architecture':'spark2_5','spark2_5.context_length':1048576,'spark2_5.block_count':36,'spark2_5.attention.head_count_kv':4,'spark2_5.attention.key_length':256,'spark2_5.attention.value_length':256,'spark2_5.attention.sliding_window':512,'spark2_5.attention.sliding_window_pattern':[1,1,1,0]*9}
  result=plan(metadata,7.66*2**30,48*2**30,24*2**30,gpu_total=24*2**30)
  row=next(r for r in result['options'] if r['context']==1048576)
  self.assertEqual(result['recommended_context'],1048576);self.assertTrue(row['fits']);self.assertTrue(row['mixed_cpu_gpu']);self.assertAlmostEqual(row['kv_gib'],36.052734375)
 def test_quantized_cache_changes_estimate(self):
  metadata={'general.architecture':'test','test.context_length':1048576,'test.block_count':8,'test.attention.head_count_kv':4,'test.attention.key_length':128,'test.attention.value_length':128}
  f16=plan(metadata,2**30,64*2**30,24*2**30)
  q8=plan(metadata,2**30,64*2**30,24*2**30,kv_type='q8_0')
  self.assertLess(q8['options'][-1]['kv_gib'],f16['options'][-1]['kv_gib'])
if __name__=='__main__':unittest.main()
