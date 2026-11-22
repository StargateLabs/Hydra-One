import copy,json,tempfile,unittest
from pathlib import Path

class ComparisonTests(unittest.TestCase):
 def report(self,device='cpu',stream=False):
  return dict(status='complete',model_file='same-model',backend='safetensors',protocol=dict(tokens=8,runs=1,warmup=0,prompt_sha256='a'*64,model_sha256='b'*64,stream=stream,configuration=dict(device=device,fit_mode='resident')),runs=[dict(public_model='fixture',arm='manual',profile='cpu',rows=[dict(warmup=False,output_tokens=8,wall_s=2,generation_ms=1000,timing_scope='model.generate_including_prefill',decode_tok_s=None,prefill_tok_s=None)])])
 def test_cpu_gpu_and_stream_compare_model_and_http_separately(self):
  from serve.benchmark_comparison import compare_reports
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'data/benchmark-checks';folder.mkdir(parents=True)
   a=self.report();b=self.report('cuda',True);b['runs'][0]['rows'][0]['wall_s']=1
   for name,report in [('a',a),('b',b)]: (folder/(name+'.json')).write_text(json.dumps(report))
   result=compare_reports(root,['a.json','b.json']);self.assertTrue(result['comparable']);self.assertEqual(result['metrics']['wall_s']['scope'],'HTTP request through response completion');self.assertEqual(result['metrics']['generation_ms']['ratios'][1],1)
   self.assertNotIn('decode_tok_s',result['metrics']);self.assertEqual(result['metrics']['wall_s']['ratios'][1],.5)
 def test_unknown_or_different_prompts_cannot_produce_ratio(self):
  from serve.benchmark_comparison import compare_reports
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'data/benchmark-checks';folder.mkdir(parents=True)
   a=self.report();b=copy.deepcopy(a);b['protocol'].pop('prompt_sha256')
   for name,report in [('a',a),('b',b)]: (folder/(name+'.json')).write_text(json.dumps(report))
   result=compare_reports(root,['a.json','b.json']);self.assertFalse(result['comparable']);self.assertEqual(result['metrics'],{});self.assertTrue(result['rows'][0]['summary'])
 def test_failed_missing_samples_and_path_escape_rejected(self):
  from serve.benchmark_comparison import compare_reports
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'data/benchmark-checks';folder.mkdir(parents=True)
   a=self.report();a['protocol']['runs']=2;(folder/'a.json').write_text(json.dumps(a));(folder/'b.json').write_text(json.dumps(self.report()))
   with self.assertRaises(ValueError):compare_reports(root,['a.json','b.json'])
   with self.assertRaises(ValueError):compare_reports(root,['../outside.json','b.json'])

if __name__=='__main__':unittest.main()
