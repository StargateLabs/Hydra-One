import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class V21Contracts(unittest.TestCase):
 def test_grant_uses_utf8_independent_of_windows_default(self):
  import os,time
  from serve.hydra_engine_v21 import load,digest
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'grant.json';counter=Path(tmp)/'counter.json'
   p.write_text(json.dumps(dict(version=21,counter=str(counter),expires_at=time.time()+60,protected={},prompt='perché già'),ensure_ascii=False),encoding='utf8')
   counter.write_text(json.dumps(dict(state='ARMED',used=0,max_requests=12,grant_sha256=digest(p))))
   with patch.dict(os.environ,HYDRA_LAB_MODE='1',HYDRA_V21_GRANT=str(p)):
    self.assertEqual(load()[0]['prompt'],'perché già')
 def test_configurable_layers_are_strict(self):
  from serve.hydra_native_text_server import hybrid_arguments
  args=hybrid_arguments('server','model',1234,32,{})
  self.assertEqual(args[args.index('-ngl')+1],'32')
  for value in (True,0,66,'65'):
   with self.assertRaises(ValueError):hybrid_arguments('s','m',1234,value,{})
 def test_counter_reserves_start_once_and_refuses_closed(self):
  from serve.hydra_engine_v21 import consume
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'counter.json';p.write_text(json.dumps(dict(state='ARMED',used=0,max_requests=12)))
   consume(p,'run-1');self.assertEqual(json.loads(p.read_text())['used'],1)
   with self.assertRaises(ValueError):consume(p,'run-1')
   p.write_text(json.dumps(dict(state='HALTED',used=1,max_requests=12)))
   with self.assertRaises(ValueError):consume(p,'run-2')
 def test_slot_transfer_binds_identity_and_detects_corruption(self):
  from serve.hydra_native_state import NativeSlot
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'state';slot=NativeSlot(root,dict(model='hash',session='run'),1024)
   calls=[]
   def api(action,payload):
    calls.append(action)
    if action=='save':(root/'state.bin').write_bytes(b'KV-real-file');return dict(n_saved=4,n_written=12)
    if action=='restore':return dict(n_restored=4,n_read=12)
    return dict(n_erased=4)
   row=slot.cycle(api);self.assertEqual(calls,['save','erase','restore']);self.assertEqual(row['restored_tokens'],4)
   (root/'state.bin').write_bytes(b'corrupted')
   with self.assertRaises(ValueError):slot.verify()
   slot.close();self.assertFalse(root.exists())
 def test_slot_oversize_rejected_before_erase(self):
  from serve.hydra_native_state import NativeSlot
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',dict(model='hash'),2);calls=[]
   def api(action,payload):
    calls.append(action);(slot.root/'state.bin').write_bytes(b'123');return dict(n_saved=1,n_written=3)
   with self.assertRaises(ValueError):slot.cycle(api)
   self.assertEqual(calls,['save']);slot.close()
 def test_event_details_do_not_change_with_live_state(self):
  from serve.hydra_native_state import frozen_detail
  state={'restored':{'tokens':22}};detail=frozen_detail(state);state['restored']['tokens']=0
  self.assertEqual(detail['restored']['tokens'],22)
 def test_checkpoint_reuses_continuation_only(self):
  from serve.hydra_native_state import continuation_messages
  messages=[dict(role='user',content='Di otto')]
  result=continuation_messages(messages,'otto','continua')
  self.assertEqual([x['role'] for x in result],['user','assistant','user'])
  self.assertEqual(messages,[dict(role='user',content='Di otto')])
 def test_native_memory_bound_rejects_before_writing(self):
  from serve.hydra_native_state import NativeSlot,state_size_bound
  bound=state_size_bound(['Vulkan0 KV buffer size = 128.00 MiB','Vulkan0 RS buffer size = 149.62 MiB'])
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},bound-1);calls=[]
   with self.assertRaisesRegex(ValueError,'BEFORE_SAVE'):slot.cycle(lambda *x:calls.append(x),expected_bound=bound)
   self.assertEqual(calls,[]);slot.close()
 def test_cancelled_state_never_calls_native_api(self):
  import threading
  from serve.hydra_native_state import NativeSlot
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},1024);cancel=threading.Event();cancel.set();calls=[]
   with self.assertRaisesRegex(ValueError,'CANCELLED'):slot.cycle(lambda *x:calls.append(x),cancel)
   self.assertEqual(calls,[]);slot.close()
 def test_native_copy_error_does_not_erase(self):
  from serve.hydra_native_state import NativeSlot
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},1024);calls=[]
   def fail(action,payload):calls.append(action);raise OSError('native save refused')
   with self.assertRaises(OSError):slot.cycle(fail)
   self.assertEqual(calls,['save']);slot.close()
 def test_checkpoint_identity_cannot_cross_sessions(self):
  from serve.hydra_native_state import NativeSlot
  with tempfile.TemporaryDirectory() as tmp:
   slot=NativeSlot(Path(tmp)/'state',{'session':'one'},1024)
   def api(action,payload):
    if action=='save':(slot.root/'state.bin').write_bytes(b'123');return dict(n_saved=1,n_written=3)
    if action=='restore':return dict(n_restored=1,n_read=3)
    return dict(n_erased=1)
   slot.cycle(api);slot.identity['session']='two'
   with self.assertRaisesRegex(ValueError,'IDENTITY'):slot.verify()
   slot.close()
 def test_unsupported_recurrent_repeat_is_rejected_by_api_contract(self):
  from serve.hydra_lab_benchmarks import validate_runner_request
  request=dict(profile='cpu',model_id='prism-ml/Ternary-Bonsai-2-27B-gguf',thinking='off',samples=2,checkpoint=True,prompt='otto',prompt_id='contract',max_tokens=16)
  with self.assertRaisesRegex(ValueError,'REPEATED_PREFIX_UNSUPPORTED'):validate_runner_request(request)
 def test_frozen_gpu_settings_include_sampler_and_cache(self):
  from serve.hydra_engine_v21 import validate_native_options
  options=dict(context=2048,threads=2,seed=42,cache_prompt=False,mmap=True,model_io='standard')
  with patch('serve.hydra_engine_v21.load',return_value=({'options':options},None)):
   validate_native_options({},dict(options))
   for field,value in [('seed',7),('cache_prompt',True),('model_io','iocp')]:
    with self.assertRaisesRegex(ValueError,'OPTIONS_MISMATCH'):validate_native_options({},dict(options,**{field:value}))
 def test_continuation_is_a_distinct_comparison_workload(self):
  from serve.hydra_native_text_server import bind_native_comparison
  row=dict(parameters={},request_json=dict(checkpoint=True,state_mode='continuation',followup='next'),configuration={},model_hash='model',runtime_hash='runtime',prompt_hash='prompt',quantization='PTQ1_0',template_hash='template')
  bind_native_comparison(row)
  self.assertEqual(row['parameters']['native_state']['followup'],'next')
 def test_launch_context_filters_secrets(self):
  from serve.hydra_native_text_server import launch_context
  row=launch_context(Path('runtime')/'server.exe',dict(LLAMA_API_KEY='private',OMP_NUM_THREADS='2',CUDA_VISIBLE_DEVICES='-1',UNRELATED_TOKEN='private'))
  self.assertEqual(row['cwd'],str(Path('runtime')))
  self.assertEqual(row['environment_filtered'],dict(OMP_NUM_THREADS='2',CUDA_VISIBLE_DEVICES='-1'))

if __name__=='__main__':unittest.main()
