import unittest,tempfile,sqlite3
import threading
from serve.hydra_lab_benchmarks import Registry,validate_runner_request

class V3Contracts(unittest.TestCase):
 def test_bounded_parameters(self):
  v=validate_runner_request(dict(profile='cpu',prompt=' Ciao ',prompt_id='v3',model_id='local/Qwen3-0.6B-Q8_0',samples=1,max_tokens=16))
  self.assertEqual(v['prompt'],' Ciao ')
  for k,value in [('samples',6),('max_tokens',129),('model_id','unknown')]:
   with self.assertRaises(ValueError):validate_runner_request({**v,k:value})
 def test_append_only_events(self):
  with tempfile.TemporaryDirectory() as d:
   r=Registry(d);row={'run_id':'a','status':'PASS','events':[{'at':'t','kind':'admission'}]};r.put(row);r.put(row)
   with r.db() as c:
    self.assertEqual(c.execute('select count(*) from run_events').fetchone()[0],1)
    with self.assertRaises(sqlite3.IntegrityError):c.execute('delete from run_events')
   row['events'][0]['kind']='rewritten'
   with self.assertRaises(ValueError):r.put(row)
 def test_complete_schema(self):
  with tempfile.TemporaryDirectory() as d:
   r=Registry(d);r.put({'run_id':'a','status':'PASS','events':[]});v=r.get('a')
   for k in ('created_at','model_id','runtime_id','config_json','request_json','metrics_json','cleanup_status','error_code'):self.assertIn(k,v)
 def test_async_exclusivity_cancel_contract_only(self):
  from serve.hydra_lab_benchmarks import Workspace
  with tempfile.TemporaryDirectory() as d:
   w=Workspace.__new__(Workspace);w.store=Registry(d);w.lock=threading.Lock();w.jobs_lock=threading.Lock();w.jobs={};w.current_cancel=None
   started=threading.Event();calls=[]
   def fixture_execute(body,_key=None,_cancel=None):
    calls.append(_key);started.set();_cancel.wait(2)
    row=w.store.get(_key);row.update(status='CANCELLED',cleanup=True);w.store.put(row)
   w.execute=fixture_execute
   body=dict(profile='cpu',prompt='fixture only',prompt_id='fixture',samples=1)
   first=w.submit(body);self.assertTrue(started.wait(1))
   try:
    second=w.submit(body);self.assertEqual(second['status'],'BLOCKED_BUSY');self.assertEqual(len(calls),1)
    w.cancel(first['run_id'])
   finally:w.shutdown()
   self.assertEqual(w.store.get(first['run_id'])['status'],'CANCELLED')
   with self.assertRaises(ValueError):w.cancel(first['run_id'])
 def test_imported_events_migrate_without_rewriting(self):
  with tempfile.TemporaryDirectory() as d:
   r=Registry(d);row={'run_id':'h','status':'IMPORTED_HISTORICAL','events':[{'kind':'historical_import','at':'original'}]};r.put(row)
   again=Registry(d)
   self.assertEqual(again.get('h')['events'],row['events'])
   with again.db() as c:self.assertEqual(c.execute('select count(*) from run_events').fetchone()[0],1)

class ArtifactIntegrity(unittest.TestCase):
 def test_output_requires_matching_hash_and_owned_name(self):
  import hashlib
  from pathlib import Path
  from serve.hydra_lab_benchmarks import read_artifact
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'warmup.wav';p.write_bytes(b'contract-fixture-not-real-audio')
   row={'artifacts':d,'artifact_hashes':{'warmup.wav':hashlib.sha256(p.read_bytes()).hexdigest()}}
   self.assertEqual(read_artifact(row,'warmup.wav'),p.read_bytes())
   with self.assertRaises(ValueError):read_artifact(row,'../warmup.wav')
   p.write_bytes(b'changed')
   with self.assertRaises(ValueError):read_artifact(row,'warmup.wav')
