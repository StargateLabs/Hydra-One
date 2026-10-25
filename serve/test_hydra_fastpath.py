"""Fast-path contracts. Fixtures below never represent native performance."""
import unittest,threading
from serve import hydra_fastpath as f
class FastPathTests(unittest.TestCase):
 def test_configuration_requires_explicit_opt_in(self):
  with self.assertRaises(ValueError):f.spec('v8-qwen-full',{},False)
 def test_offload_and_format_are_model_specific(self):
  cfg={'qwen':{'model_hash':'q','files':{'llama-server.exe':'r'}},'bonsai':{'model_hash':'b','files':{'llama-server.exe':'s'}},'rocm':{'model_hash':'q','files':{'llama-server.exe':'t'}}}
  self.assertEqual(f.spec('v8-qwen-full',cfg,True)['layers'],29)
  self.assertEqual(f.spec('v8-bonsai-control',cfg,True)['layers'],65)
  with self.assertRaises(ValueError):f.spec('v8-bonsai-rocm',cfg,True)
 def test_hash_mismatch_is_refusal_not_silent_fallback(self):
  p={'model_hash':'a','runtime_hash':'b','promoted':True}
  with self.assertRaises(ValueError):f.check_identity(p,'a','wrong')
 def test_cpu_alternative_is_explicit(self):
  self.assertEqual(f.cpu_alternative('local/Qwen3-0.6B-Q8_0'),'v8-qwen-cpu')
  with self.assertRaises(ValueError):f.cpu_alternative('unknown')
 def test_publication_requires_all_cleanup_and_persistence(self):
  self.assertTrue(f.can_publish(True,True,True,True))
  for values in ((False,True,True,True),(True,False,True,True),(True,True,False,True),(True,True,True,False)):self.assertFalse(f.can_publish(*values))
 def test_cancelled_request_never_scores(self):
  c=threading.Event();c.set()
  with self.assertRaises(InterruptedError):f.check_cancel(c)
 def test_lossless_gate_requires_fifteen_samples_and_both_workloads(self):
  def rows(ms):return {k:[{'e2e_ms':ms,'output':'same','tokens':16 if k=='short' else 96}]*15 for k in ('short','long')}
  self.assertTrue(f.performance_gate(rows(100),rows(70))['GO'])
  a=rows(70);a['long'][-1]=dict(a['long'][-1],output='different');self.assertFalse(f.performance_gate(rows(100),a)['GO'])
 def test_serial_session_rejects_foreign_and_concurrent(self):
  session=f.Session('owned',lambda b:{'native':b})
  with self.assertRaises(ValueError):session.complete({'run_id':'other','payload':{}})
  session.lock.acquire()
  try:
   with self.assertRaises(ValueError):session.complete({'run_id':'owned','payload':{}})
  finally:session.lock.release()
if __name__=='__main__':unittest.main()
class PublisherSnapshotTests(unittest.TestCase):
 def test_publisher_uses_one_consistent_snapshot(self):
  import tempfile
  from pathlib import Path
  from types import SimpleNamespace
  from serve.hydra_lab_integration import publish_existing_registry
  row=dict(run_id='a',origin='BENCHMARK',profile='cpu',prompt_id='p',model='q',backend='CPU',timestamp='2026-10-18T00:00:00+00:00',status='PASS',runtime_hash='r',artifacts='local',quality_gate='TEXT_IDENTICAL',comparison_key='x',samples=[],summary={})
  class ChangingStore:
   calls=0
   def list(self):
    self.calls+=1
    return [row] if self.calls<=2 else [row,dict(row,run_id='new')]
  store=ChangingStore()
  with tempfile.TemporaryDirectory() as d:
   publish_existing_registry(SimpleNamespace(store=store),Path(d))
  self.assertEqual(store.calls,1)
 def test_incremental_publication_does_not_rewrite_previous_files(self):
  import tempfile
  from pathlib import Path
  from types import SimpleNamespace
  from serve.hydra_lab_integration import publish_existing_registry
  row=dict(run_id='a',origin='BENCHMARK',profile='cpu',prompt_id='p',model='q',backend='CPU',timestamp='2026-10-18T00:00:00+00:00',status='PASS',runtime_hash='r',artifacts='local',quality_gate='TEXT_IDENTICAL',comparison_key='x',samples=[],summary={})
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);w=SimpleNamespace(store=SimpleNamespace(list=lambda:[row],get=lambda key:row))
   publish_existing_registry(w,root,run_id='a');p=root/'data/benchmarks/hydra-a.json';before=p.read_bytes();stamp=p.stat().st_mtime_ns
   publish_existing_registry(w,root,run_id='a');self.assertEqual(p.read_bytes(),before);self.assertEqual(p.stat().st_mtime_ns,stamp)
class CheckpointAndPayloadTests(unittest.TestCase):
 def test_checkpoint_variant_preserves_full_precision_cache(self):
  cfg={'bonsai':{'model_hash':'b','files':{'llama-server.exe':'s'}}}
  s=f.spec('v8-bonsai-nocheckpoint',cfg,True)
  self.assertEqual(s['flags'],['--ctx-checkpoints','0']);self.assertEqual(s['layers'],65);self.assertFalse(s['cache'])
 def test_app_cannot_replace_the_frozen_payload(self):
  session=f.Session('owned',lambda b:b,expected={'prompt':'frozen','n_predict':16})
  with self.assertRaises(ValueError):session.complete({'run_id':'owned','payload':{'prompt':'other','n_predict':100000}})
  self.assertEqual(session.complete({'run_id':'owned','payload':{'prompt':'frozen','n_predict':16}})['n_predict'],16)
class NativeGuardIntegrationTests(unittest.TestCase):
 def test_precancelled_native_runner_never_spawns_and_releases_ownership(self):
  self._exercise(True)
 def test_model_hash_mismatch_never_spawns_or_falls_back(self):
  self._exercise(False)
 def _exercise(self,cancelled):
  import os,tempfile
  from pathlib import Path
  from types import SimpleNamespace
  from unittest.mock import patch,MagicMock
  from serve.hydra_v7_experiments import execute
  from serve.hydra_lab_benchmarks import Registry
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);owned=[];system=SimpleNamespace(release=lambda:owned.append('system-released'));cancel=threading.Event()
   if cancelled:cancel.set()
   lab=SimpleNamespace(profile={'port':1},stop_backend=lambda:None)
   w=SimpleNamespace(lab=lab,store=Registry(root),lock=threading.Lock())
   cfg=dict(runtime=d,model=str(root/'missing.gguf'),model_hash='expected',files={'llama-server.exe':'runtime'})
   experiment=f.spec('v8-qwen-full',{'qwen':cfg},True)
   body=dict(profile='v8-qwen-full',model_id=f.QWEN,samples=5,max_tokens=16,prompt='synthetic',prompt_id='contract-fixture')
   with patch.dict(os.environ,{'HYDRA_LAB_MODE':'1'}),patch('serve.hydra_lab_benchmarks.reserve_system_runtime',return_value=system),patch('serve.hydra_lab_benchmarks.acquire_runtime_lock',return_value='fixture-lease'),patch('serve.hydra_lab_benchmarks.release_runtime_lock',side_effect=lambda x:owned.append('lease-released')),patch('serve.hydra_lab_live.LiveMonitor'),patch('serve.hydra_v7_experiments.sha',return_value='mismatch'),patch('subprocess.Popen') as spawn:
    row=execute(w,body,cancel=cancel,_experiment=experiment)
   spawn.assert_not_called();self.assertTrue(row['cleanup']);self.assertFalse(w.lock.locked());self.assertEqual(owned,['system-released','lease-released']);self.assertEqual(row['status'],'CANCELLED' if cancelled else 'FAIL');self.assertEqual(row['samples'],[])
class ManifestScopeTests(unittest.TestCase):
 def test_fastpath_binds_all_dlls_and_output_scope(self):
  import tempfile,json,os
  from pathlib import Path
  from types import SimpleNamespace
  from unittest.mock import patch
  cfg={'qwen':{'model_hash':'q','files':{'llama-server.exe':'r','ggml.dll':'real'}}}
  p=dict(configuration='v8-qwen-full',promoted=True,model_hash='q',runtime_hash='r',runtime_files={'llama-server.exe':'r','ggml.dll':'different'},allowed_output_limits=[16],gate_record_id='gate')
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'manifest.json';path.write_text(json.dumps({'models':{f.QWEN:p}}))
   store=SimpleNamespace(get=lambda key:{'status':'PASS','cleanup':True,'model_hash':'q','runtime_hash':'r','original_result':{'GO':True}})
   w=SimpleNamespace(lab=SimpleNamespace(profile={'fastpath_v8':cfg,'fastpath_manifest':str(path)}),store=store)
   body={'profile':'hydra-fastpath-v1','model_id':f.QWEN,'prompt':'fixture','max_tokens':16}
   with patch.dict(os.environ,{'HYDRA_LAB_MODE':'1'}):
    with self.assertRaises(ValueError):f.resolve_profile(w,body)
    p['runtime_files']=cfg['qwen']['files'];path.write_text(json.dumps({'models':{f.QWEN:p}}))
    with self.assertRaises(ValueError):f.resolve_profile(w,dict(body,max_tokens=96))
class SerialBarrierTests(unittest.TestCase):
 def test_foreign_runtime_stops_entire_campaign(self):
  self.assertFalse(f.may_advance({'status':'FAIL','cleanup':True,'error':'RuntimeError: foreign native runtime active; no process touched'},False,[]))
 def test_terminal_row_does_not_mean_worker_or_runtime_is_idle(self):
  row={'status':'PASS','cleanup':True}
  self.assertFalse(f.may_advance(row,True,[]));self.assertFalse(f.may_advance(row,False,[{'pid':99}]))
  self.assertTrue(f.may_advance(row,False,[]))
class GpuSafetyStopTests(unittest.TestCase):
 def test_fault_marker_blocks_gpu_but_allows_explicit_cpu(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as d:
   marker=Path(d)/'safety.json';marker.write_text('{}')
   with self.assertRaises(ValueError):f.guard_safety({'layers':29},marker)
   self.assertIsNone(f.guard_safety({'layers':0},marker))
class CpuDeviceSelectionTests(unittest.TestCase):
 def test_zero_layers_never_selects_a_gpu_device(self):
  from serve.hydra_lab_app import lab_device_arguments
  self.assertEqual(lab_device_arguments({'gpu_layers':0,'offload_tuning':True,'model_sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031'}),['--device','none'])
  self.assertEqual(lab_device_arguments({'gpu_layers':4,'offload_tuning':True,'model_sha256':'9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031'}),['--device','ROCm0'])
