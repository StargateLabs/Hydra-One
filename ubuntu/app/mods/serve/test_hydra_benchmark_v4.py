import unittest
from serve.hydra_lab_benchmarks import catalog_evidence
class ClassificationV4(unittest.TestCase):
 def test_cancellation_does_not_erase_success(self):
  row={'id':'local/Qwen3-0.6B-Q8_0','status':'ADAPTER_IMPLEMENTED'}
  runs=[{'run_id':'cancel','model':'Qwen3-0.6B-Q8_0','origin':'LIVE_APP','status':'CANCELLED','timestamp':'2'},{'run_id':'success','model':'Qwen3-0.6B-Q8_0','origin':'LIVE_APP','status':'PASS','timestamp':'1'}]
  result=catalog_evidence(row,runs);self.assertEqual(result['status'],'E2E_VERIFIED');self.assertEqual(result['last_execution_status'],'CANCELLED')
 def test_timeout_is_not_incompatibility(self):
  row={'id':'audio-cpp/audio.cpp-gguf','status':'ADAPTER_IMPLEMENTED'};runs=[{'run_id':'timeout','model':row['id'],'origin':'LIVE_APP','status':'TIMEOUT','timestamp':'1','error':'ConnectionResetError'}]
  result=catalog_evidence(row,runs);self.assertEqual(result['status'],'ADAPTER_IMPLEMENTED');self.assertEqual(result['last_execution_status'],'TIMEOUT')
 def test_metadata_failure_not_inference(self):
  row={'id':'audio-cpp/audio.cpp-gguf','status':'ADAPTER_IMPLEMENTED'};runs=[{'run_id':'remote','model':row['id'],'origin':'CAPABILITY_AUDIT','status':'FAIL','timestamp':'1','error':'ConnectionResetError'}]
  result=catalog_evidence(row,runs);self.assertNotIn('last_execution_status',result);self.assertEqual(result['status'],'ADAPTER_IMPLEMENTED')

class LiveMonitorV4(unittest.TestCase):
 def test_persistent_history_and_missing_counters(self):
  from serve.hydra_lab_live import monitor_metrics
  rows=[{'run_id':'real','origin':'E2E_TEST','status':'PASS','timestamp':'2026-10-18T06:00:00+00:00','model':'ground','profile':'test','samples':[{'e2e_ms':100,'tokens':None}]},{'run_id':'audit','origin':'CAPABILITY_AUDIT','status':'PASS','timestamp':'2026-10-18T06:00:00+00:00','model':'static','profile':'audit'}]
  m=monitor_metrics(rows);self.assertEqual(len(m['requests']),1);self.assertIsNone(m['requests'][0]['output_tokens']);self.assertIsNone(m['live']['tok_s'])
 def test_live_state_has_no_fabricated_speed(self):
  from serve.hydra_lab_live import monitor_metrics
  row={'run_id':'now','origin':'E2E_TEST','status':'RUNNING','timestamp':'2026-10-18T06:00:00+00:00','model':'test','profile':'test','events':[{'kind':'request_start'}],'samples':[]}
  m=monitor_metrics([row],row);self.assertEqual(m['live']['state'],'generating');self.assertIsNone(m['live']['tok_s'])

class MusicContractV4(unittest.TestCase):
 def test_sampling_minimum_never_exceeds_smoke_maximum(self):
  from serve.hydra_lab_native_tasks import music_request
  r=music_request('synthetic style');self.assertEqual(r['duration'],2)
  for name in ('abc_sampling','semantic_sampling'):self.assertGreaterEqual(r[name]['max_tokens'],r[name]['min_tokens'])
  self.assertEqual(r['steps'],2)

class HistoryReconciliationV4(unittest.TestCase):
 def test_native_import_is_idempotent_and_preserves_source(self):
  import tempfile,json,hashlib
  from pathlib import Path
  from serve.hydra_lab_benchmarks import Registry
  from serve.hydra_lab_history_import import import_native_reports
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'data/benchmarks';folder.mkdir(parents=True);file=folder/'original.json';file.write_text(json.dumps({'schema_version':1,'label':'historical fixture','started_at':'2026-10-01T00:00:00+00:00','engine':{'model':'fixture'},'rows':[{'wall_s':1.0,'generated':3}]}));before=file.read_bytes();store=Registry(root/'registry')
   one=import_native_reports(store,root);two=import_native_reports(store,root);self.assertEqual(one,two);self.assertEqual(len(store.list()),1);self.assertEqual(file.read_bytes(),before);self.assertEqual(store.list()[0]['origin'],'IMPORTED_HISTORICAL')
