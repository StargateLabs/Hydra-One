import json,tempfile,unittest
from pathlib import Path
from serve.hydra_feature_control import FeatureControl,FeatureError

class FeatureControlTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.control=FeatureControl(self.root,catalog=lambda:[dict(id='local/Qwen3-0.6B-Q8_0',status='E2E_VERIFIED',assets=[],runtime_path='fixture',asset_hash='fixture',reason='contract fixture only')],admission=lambda:{'state':'RELEASED'})
 def tearDown(self):self.temp.cleanup()
 def change(self,changes,**kw):return self.control.apply({'expected_version':self.control.export()['version'],'changes':changes,**kw})
 def test_v18_gpu_flags_require_their_own_controls(self):
  from unittest.mock import patch
  body=dict(profile='v8-v18-gpu-qwen',model_id='local/Qwen3-0.6B-Q8_0')
  with patch('serve.hydra_acceptance_v18.available',return_value=True),patch('serve.hydra_acceptance_v18.required_controls',return_value=[2,7]):
   self.change({'runtime.vulkan':dict(desired=True)},allow_blocked=True)
   with self.assertRaisesRegex(FeatureError,'V7-A-002'):self.control.resolve(body)
   self.change({'V7-A-002':dict(desired=True)},allow_blocked=True)
   with self.assertRaisesRegex(FeatureError,'V7-B-007'):self.control.resolve(body)
   self.change({'V7-B-007':dict(desired=True)},allow_blocked=True)
   selected=self.control.resolve(body)['required'];self.assertIn('V7-A-002',selected);self.assertIn('V7-B-007',selected)
 def test_reconciles_all_v7_groups(self):
  rows=self.control.list()['features'];self.assertEqual(sum(r['id'].startswith('V7-') for r in rows),56);self.assertTrue(all('effective' in r and 'parameters_schema' in r and 'entry_point' in r for r in rows))
 def test_on_off_controls_request(self):
  with self.assertRaisesRegex(FeatureError,'V7-H-039'):self.control.resolve({'path':'/lab/score','request':{}})
  self.change({'V7-H-039':{'desired':True}});self.assertIn('V7-H-039',self.control.resolve({'path':'/lab/score','request':{}})['required'])
  self.change({'V7-H-039':{'desired':False}})
  with self.assertRaises(FeatureError):self.control.resolve({'path':'/lab/score','request':{}})
 def test_dependencies_atomic_and_explicit(self):
  before=self.control.export()
  with self.assertRaisesRegex(FeatureError,'DEPENDENCY'):self.change({'V7-D-021':{'desired':True}})
  self.assertEqual(before,self.control.export())
  plan=self.control.preview({'V7-D-021':{'desired':True}},include_dependencies=True)
  self.assertIn('V7-D-020',plan['changes']);self.change(plan['changes']);self.assertEqual(self.control.get('V7-D-021')['effective'],'ACTIVE')
 def test_gpu_request_never_active(self):
  self.change({'runtime.vulkan':{'desired':True}},allow_blocked=True)
  self.assertEqual(self.control.get('runtime.vulkan')['effective'],'QUARANTINED')
  with self.assertRaisesRegex(FeatureError,'QUARANTINED'):self.control.resolve({'profile':'v8-qwen-full','model_id':'local/Qwen3-0.6B-Q8_0'})
 def test_mandatory_cannot_disable(self):
  with self.assertRaisesRegex(FeatureError,'MANDATORY'):self.change({'V7-I-047':{'desired':False}})
 def test_commit_limit_is_mandatory_and_not_an_rss_claim(self):
  item=self.control.get('V7-C-018')
  self.assertEqual(item['control'],'mandatory')
  self.assertTrue(item['desired'])
  self.assertIn('commit',item['description'])
  with self.assertRaisesRegex(FeatureError,'MANDATORY'):self.change({'V7-C-018':{'desired':False}})
 def test_cpu_benchmark_runtime_reuse_is_explicit(self):
  item=self.control.get('V7-A-003');self.assertEqual(item['control'],'switch')
  self.change({'V7-A-003':{'desired':True}})
  self.assertIn('V7-A-003',self.control.resolve(dict(profile='cpu',model_id='local/Qwen3-0.6B-Q8_0'))['required'])
 def test_bad_parameters_versions_secrets(self):
  for changes in ({'V7-B-009':{'parameters':{'threads':0}}},{'V7-B-011':{'parameters':{'seed':True}}},{'V7-H-039':{'key':'secret'}},{'not-a-feature':{'desired':True}}):
   with self.assertRaises(FeatureError):self.change(changes)
  with self.assertRaises(FeatureError):self.control.apply({'expected_version':999,'changes':{}})
  exported=self.control.export();exported['schema_version']=999
  with self.assertRaises(FeatureError):self.control.import_config(exported,expected_version=0)
 def test_persistence_rollback_events(self):
  self.change({'V7-H-039':{'desired':True}});other=FeatureControl(self.root,catalog=self.control.catalog,admission=self.control.admission)
  self.assertTrue(other.get('V7-H-039')['desired']);other.rollback(0,expected_version=1)
  self.assertFalse(other.get('V7-H-039')['desired']);self.assertEqual(other.export()['version'],2);self.assertEqual(len(other.history()),3)
 def test_busy_change_pending_not_runtime_mutation(self):
  self.control.admission=lambda:{'state':'RUNNING','request':{'feature_version':0}}
  self.change({'V7-B-009':{'desired':True,'parameters':{'threads':1,'affinity_cpus':1}}})
  self.assertEqual(self.control.get('V7-B-009')['effective'],'PENDING_RESTART')
 def test_unsupported_never_claims_active(self):
  self.change({'V7-F-032':{'desired':True}},allow_blocked=True)
  self.assertIn(self.control.get('V7-F-032')['effective'],('BLOCKED','UNSUPPORTED'))
 def test_rejection_keeps_original_text(self):
  body={'path':'/lab/chat','request':{'messages':[{'role':'user','content':'  e\u0301\r\n'}],'graph':False,'max_tokens':8}}
  before=json.dumps(body);self.control.resolve(body);self.assertEqual(json.dumps(body),before)
 def test_runtime_options_are_real_and_off_resets_to_reference(self):
  from serve.hydra_feature_control import runtime_options
  self.change({'V7-B-009':{'desired':True,'parameters':{'threads':1,'affinity_cpus':1}},'V7-B-011':{'desired':True,'parameters':{'context':512,'max_tokens':16,'seed':7}},'V7-B-006':{'desired':True},'V7-E-028':{'desired':False}})
  o=runtime_options(self.control);self.assertEqual((o['threads'],o['context'],o['seed']),(1,512,7));self.assertTrue(o['cache_prompt']);self.assertFalse(o['mmap'])
  self.change({'V7-B-009':{'desired':False},'V7-B-011':{'desired':False},'V7-B-006':{'desired':False},'V7-E-028':{'desired':True}})
  o=runtime_options(self.control);self.assertEqual((o['threads'],o['context'],o['seed']),(2,2048,42));self.assertFalse(o['cache_prompt']);self.assertTrue(o['mmap'])
 def test_snapshot_does_not_change_during_inflight_operation(self):
  self.change({'V7-H-039':{'desired':True}});snapshot=self.control.begin({'path':'/lab/score','request':{}})
  self.change({'V7-H-039':{'desired':False}})
  self.assertEqual(self.control.resolve({'path':'/lab/score','request':{}})['version'],snapshot['version'])
  self.control.end()
  with self.assertRaises(FeatureError):self.control.resolve({'path':'/lab/score','request':{}})
 def test_legacy_native_launcher_cannot_skip_feature_resolution(self):
  from serve.hydra_feature_control import check_native_policy
  with self.assertRaisesRegex(FeatureError,'FEATURE_CONTROL_REQUIRED'):check_native_policy(['llama-server.exe','-m','model.gguf'],{})
  check_native_policy(['llama-server.exe','--help'],{})
  check_native_policy(['llama-server.exe','-m','model.gguf'],{'feature_version':1,'feature_required':['V7-H-038']})
 def test_local_browser_session_does_not_expose_profile_key(self):
  from serve.hydra_lab_app import lab_session,lab_authenticated
  token=lab_session('private-key');self.assertNotIn('private-key',token)
  self.assertTrue(lab_authenticated({'Cookie':'hydra_lab_session='+token},'private-key','http://127.0.0.1:8091'))
  self.assertFalse(lab_authenticated({'Cookie':'hydra_lab_session='+token,'Origin':'https://external.invalid'},'private-key','http://127.0.0.1:8091'))
  self.assertFalse(lab_authenticated({'Cookie':'hydra_lab_session=wrong'},'private-key','http://127.0.0.1:8091'))
 def test_blocked_feature_probe_uses_same_effective_policy(self):
  self.change({'V7-F-032':{'desired':True}},allow_blocked=True)
  with self.assertRaisesRegex(FeatureError,'V7-F-032'):self.control.resolve({'feature_probe':'V7-F-032'})
 def test_catalog_refresh_may_write_same_registry(self):
  original=self.control.catalog
  def refresh():
   with self.control.db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS catalog_refresh(dummy INTEGER)');c.execute('INSERT INTO catalog_refresh VALUES(1)')
   return original()
  self.control.catalog=refresh;self.change({'V7-H-039':{'desired':True}})
  self.assertTrue(self.control.get('V7-H-039')['desired'])
 def test_admission_publishes_only_policy_revision_metadata(self):
  from unittest.mock import patch
  from serve import hydra_execution_v10 as coordinator
  lease={'state':'RUNNING','run_id':'policy','owner':{},'children':[],'events':[],'request':{'feature_version':7,'feature_required':['V7-H-038'],'prompt':'private text'}}
  (self.root/'lease.json').write_text(json.dumps(lease))
  with patch.object(coordinator,'ROOT',self.root):value=coordinator.admission_status()
  self.assertEqual(value['request'],{'feature_version':7,'feature_required':['V7-H-038']})
 def test_native_cpu_evidence_without_gpu_offload_counter(self):
  from serve.hydra_lab_app import parse_offload
  log='warning: no usable GPU found\nCPU_Mapped model buffer size = 604 MiB\nCPU compute buffer size = 30 MiB\n'
  self.assertEqual(parse_offload(log,requested_layers=0)['backend'],'CPU')
  self.assertEqual(parse_offload(log,requested_layers=0)['actual_layers'],0)
  self.assertIsNone(parse_offload(log,requested_layers=29)['actual_layers'])
  self.assertIsNone(parse_offload('CPU buffer only',requested_layers=0)['actual_layers'])
 def test_opt_in_existing_app_route_uses_same_feature_registry(self):
  import io
  from types import SimpleNamespace
  from serve.hydra_lab_integration import route
  result=[];handler=SimpleNamespace(headers={'X-Hydra-Lab':'key'},send_response=result.append,send_header=lambda *a:None,end_headers=lambda:None,wfile=io.BytesIO())
  route(handler,SimpleNamespace(profile={'key':'key'},features=self.control),'GET','/lab/benchmarks/api/features/list')
  self.assertEqual(result,[200]);self.assertEqual(json.loads(handler.wfile.getvalue())['version'],self.control.export()['version'])
 def test_only_explicit_unchanged_sources_survive_lab_restart(self):
  from serve.hydra_lab_app import save_sources,restore_sources
  corpus=self.root/'corpus';corpus.mkdir();source=corpus/'authorized.txt';source.write_text('synthetic owned source');(corpus/'unknown.txt').write_text('never authorized')
  save_sources(corpus,[str(source)]);sources,rejected=restore_sources(corpus);self.assertEqual(sources,[str(source.resolve())]);self.assertEqual(rejected,[])
  source.write_text('altered source');sources,rejected=restore_sources(corpus);self.assertEqual(sources,[]);self.assertTrue(rejected)
 def test_historical_success_does_not_hide_missing_asset(self):
  original=self.control.catalog()[0];self.control.catalog=lambda:[dict(original,assets=[{'path':str(self.root/'missing.gguf')}])]
  self.assertEqual(self.control.get('adapter.local/Qwen3-0.6B-Q8_0')['effective'],'BLOCKED')

if __name__=='__main__':unittest.main()
