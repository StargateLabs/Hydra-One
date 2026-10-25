import unittest,tempfile
from pathlib import Path
from serve.hydra_lab_benchmarks import Registry,comparison_key
class RegistryTests(unittest.TestCase):
 def test_persistence_and_interrupted(self):
  with tempfile.TemporaryDirectory() as d:
   r=Registry(Path(d));r.put({'run_id':'one','status':'RUNNING','events':[]});del r
   r=Registry(Path(d));self.assertEqual(r.get('one')['status'],'INTERRUPTED')
 def test_historical_idempotent(self):
  with tempfile.TemporaryDirectory() as d:
   r=Registry(Path(d));r.put({'run_id':'hist-one','status':'IMPORTED_HISTORICAL','events':[]},insert_only=True);r.put({'run_id':'hist-one','status':'IMPORTED_HISTORICAL','events':[]},insert_only=True);self.assertEqual(len(r.list()),1)
 def test_comparability(self):
  a={'model_hash':'x','runtime_hash':'r','prompt_hash':'p','parameters':{'seed':42}};self.assertEqual(comparison_key(a),comparison_key(dict(a)))
  self.assertNotEqual(comparison_key(a),comparison_key({**a,'runtime_hash':'different'}))
if __name__=='__main__':unittest.main()

class ProbeEnvironment(unittest.TestCase):
 def test_probe_visibility_is_local(self):
  from serve.hydra_lab_benchmarks import probe_environment
  source={'HIP_VISIBLE_DEVICES':'','ROCR_VISIBLE_DEVICES':'','GGML_BACKEND_PATH':'wrong'}
  result=probe_environment(source)
  self.assertEqual(result['HIP_VISIBLE_DEVICES'],'0');self.assertEqual(result['ROCR_VISIBLE_DEVICES'],'0');self.assertNotIn('GGML_BACKEND_PATH',result);self.assertEqual(source['HIP_VISIBLE_DEVICES'],'')

class AppRestart(unittest.TestCase):
 def test_lab_reopens_own_graph_and_registry(self):
  from serve.hydra_lab_app import Lab
  with tempfile.TemporaryDirectory() as d:
   p={'data':d};one=Lab(p);one.close();two=Lab(p);self.assertTrue(two.g.writable);two.close()

class IntegrationContracts(unittest.TestCase):
 def test_execution_opt_in(self):
  from unittest.mock import patch
  from serve.hydra_lab_integration import render_lab_html,service_lab
  source=b'<html><head></head></html>'
  with patch.dict('os.environ',{'HYDRA_LAB_MODE':'0'}):
   self.assertEqual(render_lab_html(source),source)
   with self.assertRaises(ValueError):service_lab(object())
  with patch.dict('os.environ',{'HYDRA_LAB_MODE':'1'}):self.assertIn(b'window.HYDRA_LAB_MODE=true',render_lab_html(source))
 def test_runtime_lease_is_exclusive(self):
  from serve.hydra_lab_benchmarks import acquire_runtime_lock,release_runtime_lock
  with tempfile.TemporaryDirectory() as d:
   handle=acquire_runtime_lock(d)
   try:
    with self.assertRaises(ValueError):acquire_runtime_lock(d)
   finally:release_runtime_lock(handle)
   handle=acquire_runtime_lock(d);release_runtime_lock(handle)
 def test_missing_metrics_are_not_zero(self):
  from serve.hydra_lab_benchmarks import summary
  self.assertIsNone(summary([{'e2e_ms':1}])['decode_tps'])
  self.assertEqual(summary([{'e2e_ms':1},{'e2e_ms':3}])['e2e_ms']['median'],2)
 def test_historical_import_is_real_and_idempotent(self):
  from serve.hydra_lab_benchmarks import import_history
  with tempfile.TemporaryDirectory() as d:
   store=Registry(Path(d));source=Path(__file__).resolve().parents[1]/'hydra-engine/performance_optimization_e2e_v1_retest_20261018_012618'
   import_history(store,source);import_history(store,source);self.assertEqual(len(store.list()),6)
   self.assertTrue(all(r['origin']=='IMPORTED_HISTORICAL' for r in store.list()))
 def test_publish_to_existing_archive_preserves_origin(self):
  from serve.hydra_lab_benchmarks import import_history
  from serve.hydra_lab_integration import publish_existing_registry,published_rows,existing_reports
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as d:
   store=Registry(Path(d)/'source');source=Path(__file__).resolve().parents[1]/'hydra-engine/performance_optimization_e2e_v1_retest_20261018_012618';import_history(store,source);workspace=SimpleNamespace(store=store)
   self.assertEqual(publish_existing_registry(workspace,Path(d)/'app'),6);rows=published_rows(Path(d)/'app');self.assertEqual(len(rows),6);self.assertTrue(all(r['origin']=='IMPORTED_HISTORICAL' for r in rows));self.assertTrue(all(r['hydra_run_id'] for r in existing_reports(workspace)))

class MeasurementScope(unittest.TestCase):
 def test_different_timing_boundaries_cannot_be_equivalent(self):
  row={'model_hash':'x','runtime_hash':'r','prompt_hash':'p','parameters':{'seed':42},'quantization':'q','template_hash':'t'}
  self.assertNotEqual(comparison_key({**row,'measurement_scope':'client_http_round_trip'}),comparison_key({**row,'measurement_scope':'server_lab_request_wrapper'}))

class SharedReservation(unittest.TestCase):
 def test_existing_system_reservation_is_never_stolen(self):
  from serve.gpu_lease import GpuLease
  from serve.hydra_lab_benchmarks import reserve_system_runtime
  with tempfile.TemporaryDirectory() as d:
   owner=GpuLease(d,'other-owner').acquire();before=owner.path.read_bytes()
   try:
    with self.assertRaises(RuntimeError):reserve_system_runtime(d)
    self.assertEqual(owner.path.read_bytes(),before)
   finally:owner.release()
   mine=reserve_system_runtime(d);mine.release();self.assertFalse(mine.path.exists())
