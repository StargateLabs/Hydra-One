"""Small, local admission/lifecycle contracts. Never loads a model or contacts a node."""
import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock

class Contracts(unittest.TestCase):
 def identity(self):
  return dict(sha256='a'*64,runtime_sha256='f'*64,tokenizer_sha256='b'*64,vocabulary_sha256='c'*64,architecture='qwen35',vocab_size=256,bos=1,eos=[2],context=512,sequence_format='tokens-v1')
 def test_speculative_identity_and_sequences(self):
  from serve.hydra_capability_contracts import speculative_contract,CapabilityError
  a=self.identity();b=dict(a,sha256='d'*64)
  self.assertEqual(speculative_contract(a,b,[1,3],[1,3],4)['status'],'COMPATIBLE_METADATA_ONLY')
  for altered in (dict(b,tokenizer_sha256='e'*64),dict(b,bos=True),a):
   with self.assertRaises(CapabilityError):speculative_contract(a,altered,[1,3],[1,3],4)
  with self.assertRaises(CapabilityError):speculative_contract(a,b,[1,3],[1,4],4)
 def test_full_model_budget_and_identity(self):
  from serve.hydra_capability_contracts import full_model_budget,CapabilityError
  sizes=dict(weights=100,state=20,kv=30,workspace=40,runtime_buffers=10)
  self.assertEqual(full_model_budget(self.identity(),sizes,220,20)['total_bytes'],220)
  for bad in (dict(sizes,kv=None),dict(sizes,weights=True),dict(sizes,workspace=-1)):
   with self.assertRaises(CapabilityError):full_model_budget(self.identity(),bad,220,20)
  with self.assertRaises(CapabilityError):full_model_budget(self.identity(),sizes,219,20)
  missing=self.identity();missing.pop('runtime_sha256')
  with self.assertRaises(CapabilityError):full_model_budget(missing,sizes,220,20)
 def test_moe_geometry_and_dense_rejection(self):
  from serve.hydra_capability_contracts import moe_contract,CapabilityError
  model=dict(self.identity(),n_expert=512,n_layers=48,hidden=2560,ff=640)
  pack=dict(model,format='planarQ2',sha256='e'*64,backbone_sha256=model['sha256'])
  self.assertEqual(moe_contract(model,pack,'cpu-planar-q2')['status'],'COMPATIBLE_METADATA_ONLY')
  with self.assertRaises(CapabilityError):moe_contract(dict(model,n_expert=0),pack,'cpu-planar-q2')
  with self.assertRaises(CapabilityError):moe_contract(model,dict(pack,hidden=4096),'cpu-planar-q2')
 def test_request_gate_cannot_bypass_disabled_feature(self):
  from serve.hydra_capability_contracts import guard_request,CapabilityError
  for body in ({'speculative':True},{'moe':True},{'weight_tiering':True},{'remote':{'address':'127.0.0.1'}},{'model_id':'colibri/full35B'}):
   with self.assertRaises(CapabilityError):guard_request(body)
  self.assertEqual(guard_request({'model_id':'local/Qwen3-0.6B-Q8_0'}),[])
 def test_runtime_ownership_and_no_fake_weight_eviction(self):
  from serve.hydra_capability_contracts import RuntimeOwnership,CapabilityError
  child=Mock();child.poll.return_value=None
  owner=RuntimeOwnership('session','a'*64);owner.attach(child);owner.begin_sequence()
  with self.assertRaises(CapabilityError):owner.close()
  with self.assertRaises(CapabilityError):owner.unload_weights()
  owner.end_sequence();child.poll.return_value=0;owner.close();owner.close()
  self.assertEqual(owner.state,'CLOSED')
 def test_cached_tokens_are_strict_runtime_evidence(self):
  from serve.hydra_native_state import native_cached_tokens
  self.assertEqual(native_cached_tokens({'usage':{'prompt_tokens_details':{'cached_tokens':3}}},8,5),3)
  for count in (True,-1,9,1.5):
   with self.assertRaises(ValueError):native_cached_tokens({'usage':{'prompt_tokens_details':{'cached_tokens':count}}},8,5)
  with self.assertRaises(ValueError):native_cached_tokens({},8,5)
 def test_slot_destination_and_position_checked_before_transfer(self):
  from serve.hydra_native_state import NativeSlot
  with tempfile.TemporaryDirectory() as root:
   slot=NativeSlot(Path(root)/'state',dict(model='a',session='s',context=4),1024)
   api=Mock()
   with self.assertRaisesRegex(ValueError,'DESTINATION'):slot.cycle(api,destination_identity=dict(model='b',session='s',context=4))
   api.assert_not_called();slot.close()

class ConsumerLinks(unittest.TestCase):
 def test_compatibility_metadata_reaches_the_shared_gate(self):
  from serve.hydra_capability_contracts import guard_request,CapabilityError,remote_contract
  identity=Contracts().identity()
  with self.assertRaisesRegex(CapabilityError,'COMPLETE_MEMORY'):
   guard_request({'full35b':dict(identity=identity,components={},limit_bytes=100,safety_margin_bytes=10)})
  with self.assertRaisesRegex(CapabilityError,'DRAFT_TARGET_MISMATCH'):
   guard_request({'speculative':dict(draft=identity,target=dict(identity,sha256='d'*64,tokenizer_sha256='e'*64),draft_sequence=[1],target_sequence=[1],max_draft_tokens=1)})
  node=dict(node_id='fixture',endpoint='https://node.invalid',authorization_sha256='a'*64,runtime_sha256='b'*64,model_sha256='c'*64,tokenizer_sha256='d'*64,tls_certificate_sha256='e'*64)
  task=dict(node,request_id='one')
  self.assertFalse(remote_contract(node,task,10)['execution_enabled'])
  with self.assertRaisesRegex(CapabilityError,'AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED'):
   guard_request({'remote':dict(node=node,task=task,timeout_seconds=10)})
  with self.assertRaisesRegex(CapabilityError,'REMOTE_IDENTITY_MISMATCH'):
   remote_contract(node,dict(task,model_sha256='f'*64),10)
 def test_loader_control_is_not_lost_by_entrypoint_resolution(self):
  from serve.hydra_feature_control import FeatureControl,feature_number
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as root:
   control=FeatureControl(root,catalog=lambda:[dict(id='local/Qwen3-0.6B-Q8_0',status='E2E_VERIFIED')],admission=lambda:dict(state='RELEASED'))
   ids={feature_number(k):k for k in control.defs() if feature_number(k)}
   control.apply(dict(expected_version=0,changes={ids[29]:dict(desired=True),ids[28]:dict(desired=False)},allow_blocked=True))
   with patch.object(control,'_effective',return_value=('ACTIVE','software fixture')):
    for body in ({'path':'/lab/chat','request':{}},{'model_id':'local/Qwen3-0.6B-Q8_0','profile':'cpu'}):
     self.assertIn(ids[29],control.resolve(body)['required'])
   control.apply(dict(expected_version=1,changes={ids[29]:dict(desired=False)}))
   self.assertNotIn(ids[29],control.resolve({'path':'/lab/chat','request':{}})['required'])
 def test_entrypoints_reject_before_child_or_database(self):
  from serve.hydra_capability_contracts import CapabilityError
  from serve.hydra_feature_control import FeatureControl
  from serve.hydra_execution_v10 import exclusive_execute
  from serve.hydra_native_text_server import execute
  from serve.hydra_lab_app import Lab
  from unittest.mock import patch
  control=FeatureControl.__new__(FeatureControl);control.defs=Mock()
  with self.assertRaises(CapabilityError):control.resolve({'speculative':True})
  control.defs.assert_not_called()
  worker=Mock();wrapped=exclusive_execute(worker)
  with patch('serve.hydra_execution_v10.Reservation') as reservation:
   with self.assertRaises(CapabilityError):wrapped(Mock(),{'moe':True})
   reservation.assert_not_called();worker.assert_not_called()
  with patch('serve.hydra_native_text_server.guarded_popen') as spawn:
   with self.assertRaises(CapabilityError):execute(Mock(),{'weight_tiering':True})
   spawn.assert_not_called()
  lab=Lab.__new__(Lab);lab.profile={'remote':True}
  with self.assertRaises(CapabilityError):lab.start()
 def test_state_position_and_session_options(self):
  from serve.hydra_native_state import NativeSlot,session_identity
  options={'seed':42};identity=session_identity('a'*64,'b'*64,'session',4,0,'off',options);options['seed']=43
  self.assertEqual(identity['options']['seed'],42)
  with tempfile.TemporaryDirectory() as root:
   slot=NativeSlot(Path(root)/'state',identity,1024);calls=[]
   def api(action,payload):
    calls.append(action);(slot.root/'state.bin').write_bytes(b'abcd');return dict(n_written=4,n_saved=5)
   with self.assertRaisesRegex(ValueError,'POSITION'):slot.cycle(api,destination_identity=identity)
   self.assertEqual(calls,['save']);self.assertEqual(slot.state,'FAILED');slot.close()

if __name__=='__main__':unittest.main(failfast=True)
