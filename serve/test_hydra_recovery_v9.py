import unittest,tempfile,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve import hydra_fastpath as f
class RecoveryTests(unittest.TestCase):
 def test_profile_resolution_invokes_safety_stop(self):
  w=SimpleNamespace(lab=SimpleNamespace(profile={'fastpath_v8':{'qwen':{'model_hash':'q','files':{'llama-server.exe':'r'}}}}))
  with patch.dict('os.environ',{'HYDRA_LAB_MODE':'1'}),patch.object(f,'guard_safety',side_effect=ValueError('safety stop')):
   with self.assertRaisesRegex(ValueError,'safety stop'):f.resolve_profile(w,{'profile':'v8-qwen-full'})
 def test_greedy_sampler_is_not_reported_as_rng_failure(self):
  from serve.hydra_recovery_diagnostics import analyze_samples
  samples=[{'output':'a','response':{'generation_settings':{'seed':42,'temperature':0},'tokens':[],'timings':{'cache_n':0}}},{'output':'b','response':{'generation_settings':{'seed':42,'temperature':0},'tokens':[],'timings':{'cache_n':0}}}]
  r=analyze_samples(samples);self.assertFalse(r['text_repeatable']);self.assertEqual(r['rng_cause'],'NOT_ESTABLISHED');self.assertFalse(r['output_token_ids_verified']);self.assertEqual(r['cache_hit_samples'],0)
 def test_cache_hit_uses_native_reused_counter_not_final_cache_size(self):
  from serve.hydra_recovery_diagnostics import analyze_samples
  r=analyze_samples([{'output':'a','response':{'tokens_cached':405,'timings':{'cache_n':0}}}]);self.assertEqual(r['cache_hit_samples'],0)
 def test_native_fault_classification_does_not_diagnose_physical_gpu(self):
  from serve.hydra_recovery_diagnostics import classify_native_error
  r=classify_native_error('decode failed: ErrorDeviceLost');self.assertEqual(r['error_code'],'GPU_DEVICE_LOST');self.assertTrue(r['stop_gpu_sequence']);self.assertEqual(r['physical_gpu_failure'],'NOT_ESTABLISHED')
if __name__=='__main__':unittest.main()
class FaultEvidenceTests(unittest.TestCase):
 def test_environment_evidence_never_contains_credentials(self):
  from serve.hydra_recovery_diagnostics import safe_environment
  r=safe_environment({'API_KEY':'secret','TOKEN':'secret','OMP_NUM_THREADS':'2','GGML_BACKEND_PATH':'local','PATH':'private'})
  self.assertEqual(r,{'OMP_NUM_THREADS':'2','GGML_BACKEND_PATH':'local'})
 def test_device_loss_creates_stop_evidence_without_changing_history(self):
  from serve.hydra_recovery_diagnostics import persist_fault
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);marker=root/'stop.json';evidence=root/'evidence';evidence.mkdir()
   r=persist_fault('device lost on Vulkan0',marker,evidence,{'run_id':'new'})
   self.assertTrue(marker.is_file());self.assertTrue(r['stop_gpu_sequence']);first=marker.read_bytes()
   persist_fault('ErrorDeviceLost',marker,evidence,{'run_id':'second'})
   self.assertEqual(marker.read_bytes(),first)
 def test_non_device_error_does_not_create_gpu_stop(self):
  from serve.hydra_recovery_diagnostics import persist_fault
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);persist_fault('invalid request',root/'stop.json',root,{'run_id':'x'});self.assertFalse((root/'stop.json').exists())
