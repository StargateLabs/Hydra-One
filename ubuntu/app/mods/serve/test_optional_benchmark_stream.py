import tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from serve.optional_benchmark import OptionalBenchmark

class Manager:
 def __init__(self,root):self.root=root;self.conversation_lock=threading.Lock();self.requests=[]
 def status(self):return dict(status='ready',public_model='fixture',model='fixture',backend='safetensors',mode='safetensors',device='cpu',fit_mode='resident')
 def chat(self,payload,cancel):
  self.requests.append(payload)
  if payload['stream']:
   yield {'choices':[{'delta':{'role':'assistant'}}]}
   yield {'choices':[{'delta':{'content':'hello'}}]}
   yield {'choices':[{'delta':{'content':' world'},'finish_reason':'length'}]}
   yield {'choices':[],'usage':{'completion_tokens':2},'timings':{'generation_ms':50,'timing_scope':'model.generate_including_prefill'}}
  else:yield {'choices':[{'message':{'content':'hello world'}}],'usage':{'completion_tokens':2}}

class OptionalStreamTests(unittest.TestCase):
 def test_stream_accumulates_content_usage_and_keeps_model_scope(self):
  with tempfile.TemporaryDirectory() as directory:
   manager=Manager(Path(directory));benchmark=OptionalBenchmark(manager)
   with patch('serve.optional_benchmark.threading.Thread') as thread:
    job=benchmark.start(dict(runs=3,tokens=32,prompt='hello',stream=True))
   self.assertTrue(job['protocol']['stream']);self.assertEqual(len(job['protocol']['prompt_sha256']),64)
   benchmark._run(manager.status(),'hello',False)
   result=benchmark.status()[0];self.assertEqual(result['status'],'complete',result)
   row=result['results'][0]['series'][1]
   self.assertEqual(row['output_tokens'],2);self.assertGreater(row['ttft_s'],0);self.assertEqual(row['generation_ms'],50);self.assertIsNone(row['decode_tok_s']);self.assertTrue(manager.requests[0]['stream'])
 def test_false_remains_default_and_stream_type_is_validated(self):
  with tempfile.TemporaryDirectory() as directory:
   manager=Manager(Path(directory));benchmark=OptionalBenchmark(manager)
   with self.assertRaises(ValueError):benchmark.start(dict(stream='true'))
   with patch('serve.optional_benchmark.threading.Thread'):job=benchmark.start(dict(runs=3,tokens=32))
   self.assertFalse(job['protocol']['stream']);benchmark._run(manager.status(),'hello',False)
   self.assertEqual(benchmark.status()[0]['status'],'complete')
   self.assertIsNone(benchmark.status()[0]['results'][0]['series'][1].get('ttft_s'))

if __name__=='__main__':unittest.main()
