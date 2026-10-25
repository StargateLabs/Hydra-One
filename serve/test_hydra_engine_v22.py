import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from serve.hydra_native_state import NativeSlot
class V22Contracts(unittest.TestCase):
 def test_raw_transport_cannot_reopen_after_revocation(self):
  import http.client
  from serve.hydra_http_pool import SerialConnectionPool
  raw=http.client.HTTPConnection('127.0.0.1',1);raw.connect=Mock()
  pool=SerialConnectionPool(factory=lambda *a,**kw:raw);pool.connection('127.0.0.1',1,1);pool.close()
  with self.assertRaises(http.client.NotConnected):raw.send(b'x')
  raw.connect.assert_not_called()
 def test_cancellation_during_connect_revokes_its_result(self):
  from serve.hydra_http_pool import SerialConnectionPool
  raw=Mock();raw.sock=None;pool=SerialConnectionPool(factory=lambda *a,**kw:raw)
  connection=pool.connection('127.0.0.1',1,1);raw.connect.side_effect=pool.close
  with self.assertRaisesRegex(RuntimeError,'REVOKED'):connection.connect()
 def test_rejected_gpu_request_without_grant_does_not_break_cleanup(self):
  import os
  from unittest.mock import patch
  from serve.hydra_execution_v10 import notify_gpu_fault
  with patch.dict(os.environ,{},clear=True),patch('serve.hydra_engine_v21.halt') as halt:
   self.assertFalse(notify_gpu_fault({'profile':'v21-bonsai-hybrid'},'not admitted','unit'))
   halt.assert_not_called()
 def test_temp_state_cleanup_cannot_be_reported_as_complete(self):
  from serve.hydra_execution_v10 import require_application_cleanup,AdmissionError
  require_application_cleanup(dict(cleanup=True,native_state_cleanup=True))
  with self.assertRaisesRegex(AdmissionError,'STATE_CLEANUP'):require_application_cleanup(dict(cleanup=True,native_state_cleanup=False))
 def test_lab_transport_toggle_reaches_the_backend(self):
  from serve.hydra_lab_app import attach_http_pool
  lab=SimpleNamespace(features=SimpleNamespace(setting=lambda number:{'desired':True}));backend=SimpleNamespace()
  attach_http_pool(lab,backend);self.assertEqual(backend.connection_factory,lab.http_pool.connection);lab.http_pool.close()
  lab.features.setting=lambda number:{'desired':False};other=SimpleNamespace();attach_http_pool(lab,other)
  self.assertFalse(hasattr(other,'connection_factory'))
 def test_continuation_is_recompiled_against_its_own_budget(self):
  from unittest.mock import patch
  from serve.hydra_native_text_server import compile_native_context
  body=dict(thinking='off',max_tokens=16)
  with patch('serve.hydra_native_text_server.native_json',side_effect=[{'prompt':'prepared'},{'tokens':[1]*30}]):
   row=compile_native_context(1,'key',[{'role':'user','content':'continuation'}],body,128)
   self.assertEqual(row['compiled_prompt_tokens'],30)
  with patch('serve.hydra_native_text_server.native_json',side_effect=[{'prompt':'prepared'},{'tokens':[1]*80}]):
   with self.assertRaisesRegex(ValueError,'BUDGET'):compile_native_context(1,'key',[],body,128)
 def slot_api(self,slot):
  def api(action,payload):
   if action=='save':(slot.root/'state.bin').write_bytes(b'123');return dict(n_saved=2,n_written=3)
   if action=='erase':return dict(n_erased=2)
   return dict(n_restored=2,n_read=3)
  return api
 def test_sidecar_tampering_invalidates_state(self):
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},1024);slot.cycle(self.slot_api(slot))
   (slot.root/'identity.json').write_text('{}')
   with self.assertRaises(ValueError):slot.verify()
   slot.close();slot.close()
 def test_erase_must_attest_the_saved_tokens(self):
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},1024);api=self.slot_api(slot);calls=[]
   def wrong(action,payload):calls.append(action);return dict(n_erased=0) if action=='erase' else api(action,payload)
   with self.assertRaises(ValueError):slot.cycle(wrong)
   self.assertNotIn('restore',calls);slot.close()
 def test_failed_transfer_cannot_be_retried_in_place(self):
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},1024)
   with self.assertRaises(OSError):slot.cycle(Mock(side_effect=OSError('save failed')))
   with self.assertRaises(ValueError):slot.cycle(self.slot_api(slot))
   slot.close()
 def test_pool_updates_live_socket_deadline_and_revokes_leases(self):
  from serve.hydra_http_pool import SerialConnectionPool
  raw=Mock();raw.sock=Mock();raw.getresponse.return_value=SimpleNamespace(length=0,isclosed=lambda:True,will_close=False)
  pool=SerialConnectionPool(factory=Mock(return_value=raw));first=pool.connection('127.0.0.1',1,1);first.getresponse();first.close()
  second=pool.connection('127.0.0.1',1,8);raw.sock.settimeout.assert_called_with(8)
  with self.assertRaises(RuntimeError):first.request('GET','/')
  pool.close()
  with self.assertRaises(RuntimeError):second.connect()
 def test_stale_repository_selection_refused_before_compilation(self):
  import hashlib
  from serve.hydra_graphify_runtime import revalidate_selection
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'source.py';p.write_bytes(b'old');row=dict(path=str(p),bytes=3,source_sha256=hashlib.sha256(b'old').hexdigest());revalidate_selection(row)
   p.write_bytes(b'new')
   with self.assertRaisesRegex(ValueError,'CHANGED'):revalidate_selection(row)
 def test_checkpoint_helper_rejects_lexical_parent_escape(self):
  import hashlib
  from serve.hydra_scoring_runtime import attested_helper
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);folder=root/'owned';folder.mkdir();binary=root/'outside.exe';binary.write_bytes(b'fixture')
   manifest=folder/'manifest.json';manifest.write_text(json.dumps(dict(executable=str(folder/'..'/'outside.exe'),sha256=hashlib.sha256(b'fixture').hexdigest())))
   with self.assertRaises(ValueError):attested_helper(manifest,'TEST')

class V22LoaderWiring(unittest.TestCase):
 def test_cpu_candidates_are_selected_without_starting_them(self):
  from serve.hydra_native_text_server import select_loader
  from serve.hydra_lab_app import model_loader_runtime
  root=Path(__file__).resolve().parents[1]/'hydra-engine/engine_completion_v22'
  manifest=json.loads((root/'prism-loader-manifest.json').read_text(encoding='utf8'))
  cat=dict(id='prism-ml/Ternary-Bonsai-2-27B-gguf',asset_hash=manifest['model_hash'],runtime_path='reference')
  self.assertIs(select_loader(cat,{'model_io':'standard'}),cat)
  chosen=select_loader(cat,dict(model_io='iocp',mmap=False))
  self.assertEqual(Path(chosen['runtime_path']),root/'prism-cpu-build/bin/llama-server.exe')
  reference,_,env=model_loader_runtime('reference',dict(model_io='standard'),0);self.assertEqual(reference,Path('reference'));self.assertEqual(env,{})
  runtime,info,env=model_loader_runtime('reference',dict(model_io='iocp',mmap=False),0)
  self.assertEqual(runtime,root/'qwen-cpu-build/bin');self.assertEqual(env['HYDRA_MODEL_IO'],'iocp')
 def test_http_control_is_required_by_the_lab_resolver(self):
  from serve.hydra_feature_control import FeatureControl
  with tempfile.TemporaryDirectory() as tmp:
   model='local/Qwen3-0.6B-Q8_0';control=FeatureControl(Path(tmp),catalog=lambda:[dict(id=model,status='E2E_VERIFIED',assets=[],runtime_path='fixture',asset_hash='fixture',reason='software contract only')],admission=lambda:dict(state='RELEASED'))
   changes={'V7-G-035':dict(desired=True),'V7-H-038':dict(desired=True),'adapter.'+model:dict(desired=True)}
   control.apply(dict(expected_version=control.export()['version'],changes=changes))
   self.assertIn('V7-G-035',control.resolve(dict(path='/lab/chat',request={}))['required'])
   control.apply(dict(expected_version=control.export()['version'],changes={'V7-G-035':dict(desired=False)}))
   self.assertNotIn('V7-G-035',control.resolve(dict(path='/lab/chat',request={}))['required'])
if __name__=='__main__':unittest.main()
