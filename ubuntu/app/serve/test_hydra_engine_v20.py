import unittest
from serve.hydra_native_text_server import server_arguments,server_request
class V20NativeOptions(unittest.TestCase):
 def test_native_controls_reach_cpu_command_and_request(self):
  options=dict(context=1024,threads=1,mmap=False,cache_prompt=True,seed=7)
  args=server_arguments('server.exe','model.gguf',1234,options=options)
  self.assertEqual(args[args.index('-c')+1],'1024')
  self.assertEqual(args[args.index('-t')+1],'1')
  self.assertIn('--no-mmap',args)
  self.assertEqual(args[args.index('--device')+1],'none')
  req=server_request(dict(prompt='x',thinking='off',max_tokens=96),options=options)
  self.assertTrue(req['cache_prompt']);self.assertEqual(req['seed'],7)
 def test_cpu_rejects_gpu_option_leak(self):
  with self.assertRaises(ValueError):server_arguments('s','m',1,options=dict(gpu_layers=20))

class V20TicketTests(unittest.TestCase):
 def test_counter_is_finite_durable_and_never_rearms(self):
  import tempfile,json
  from pathlib import Path
  from serve.hydra_engine_v20 import consume
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'counter.json';p.write_text(json.dumps(dict(state='ARMED',used=0,max_requests=12)))
   for i in range(12):consume(p,'run'+str(i))
   self.assertEqual(json.loads(p.read_text())['used'],12)
   with self.assertRaises(ValueError):consume(p,'extra')
 def test_duplicate_request_cannot_forward_twice(self):
  import tempfile,json
  from pathlib import Path
  from serve.hydra_engine_v20 import consume
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'counter.json';p.write_text(json.dumps(dict(state='ARMED',used=0,max_requests=12)))
   consume(p,'same')
   with self.assertRaises(ValueError):consume(p,'same')
   self.assertEqual(json.loads(p.read_text())['used'],1)

class V20DeadlineTests(unittest.TestCase):
 def test_bonsai_receives_bounded_27b_deadline(self):
  from serve.hydra_native_text_server import request_deadline
  self.assertEqual(request_deadline('prism-ml/Ternary-Bonsai-2-27B-gguf'),600)
  self.assertEqual(request_deadline('other'),180)

class V20HybridTests(unittest.TestCase):
 def test_explicit_partial_offload_keeps_cpu_profile_separate(self):
  from serve.hydra_native_text_server import hybrid_arguments
  args=hybrid_arguments('s','m',1234,16,dict(context=1024,threads=2,mmap=True))
  self.assertEqual(args[args.index('-ngl')+1],'16')
  self.assertEqual(args[args.index('--device')+1],'Vulkan0')
  self.assertIn('--no-warmup',args)
 def test_unknown_offload_is_refused(self):
  from serve.hydra_native_text_server import hybrid_arguments
  for n in (-1,0,99,True):
   with self.assertRaises(ValueError):hybrid_arguments('s','m',1234,n,{})

class V20AdmissionTests(unittest.TestCase):
 def test_exact_spawn_rejects_aliases_and_wrong_model(self):
  from unittest.mock import patch
  from serve.hydra_engine_v20 import allow_spawn
  g=dict(runtime='X:/prism',commands={'job':['X:\\prism\\llama-server.exe']})
  with patch('serve.hydra_engine_v20.load',return_value=(g,None)):
   self.assertFalse(allow_spawn(dict(profile='cpu'),['anything']))
   self.assertFalse(allow_spawn(dict(profile='v20-bonsai-hybrid-16',model='other',workload='job'),['anything']))
 def test_closed_or_halted_ticket_never_consumes(self):
  import json,tempfile
  from pathlib import Path
  from serve.hydra_engine_v20 import consume
  for status in ('HALTED','CLOSED'):
   with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'s.json';p.write_text(json.dumps(dict(state=status,used=1,max_requests=12)))
    with self.assertRaises(ValueError):consume(p,'x')
    self.assertEqual(json.loads(p.read_text())['used'],1)

class V20ReuseTests(unittest.TestCase):
 def test_native_reuse_is_explicit_and_bounded(self):
  from serve.hydra_native_text_server import repetition_count
  self.assertEqual(repetition_count(dict(samples=2),True),2)
  with self.assertRaises(ValueError):repetition_count(dict(samples=2),False)
  with self.assertRaises(ValueError):repetition_count(dict(samples=3),True)
 def test_native_cpu_two_samples_reach_admission(self):
  from serve.hydra_lab_benchmarks import validate_runner_request
  body=dict(profile='cpu',model_id='prism-ml/Ternary-Bonsai-2-27B-gguf',prompt='Fonte: il codice è 47. Qual è il codice?',prompt_id='cache-context',samples=2,max_tokens=16,thinking='off')
  self.assertEqual(validate_runner_request(body)['samples'],2)

class V20ContextTests(unittest.TestCase):
 def test_context_compiler_is_shared_and_preserves_source_identity(self):
  from serve.hydra_graph import source_context_block
  block=source_context_block([dict(content='codice47',source='doc',source_sha256='abc',id='node',evidence='verified',source_span=[0,8])])
  self.assertIn('BEGIN UNTRUSTED RETRIEVED SOURCE DATA',block)
  self.assertIn('codice47',block);self.assertIn('abc',block);self.assertIn('node',block)
 def test_native_graph_off_does_no_retrieval(self):
  from unittest.mock import Mock
  from serve.hydra_native_text_server import retrieve_context
  lab=Mock();messages,trace=retrieve_context(lab,dict(prompt='x'))
  self.assertEqual(messages,[dict(role='user',content='x')]);self.assertIsNone(trace);lab.retrieve.assert_not_called()

class V20CompactContextTests(unittest.TestCase):
 def test_compact_context_keeps_content_and_reference_keys(self):
  from serve.hydra_graph import source_context_block
  rows=[dict(content='Codice CacheV20: 47.',source='C:/very-long-owned-source.txt',source_sha256='a'*64,id='b'*64,evidence='verified',source_span=[0,19])]
  compact=source_context_block(rows,compact=True)
  self.assertIn('Codice CacheV20: 47.',compact);self.assertIn('source_id',compact)
  self.assertLess(len(compact),len(source_context_block(rows)))
  self.assertNotIn('C:/very-long',compact)

class V20PublicStatusTests(unittest.TestCase):
 def test_status_reveals_only_bounded_requests_not_private_runtime(self):
  from unittest.mock import patch
  from serve.hydra_engine_v20 import public_status
  import tempfile,json
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'s.json';p.write_text(json.dumps(dict(state='ARMED',used=1,max_requests=12)))
   g=dict(runtime='private',requests={'x':dict(profile='v20-bonsai-hybrid-16',prompt='x')})
   with patch('serve.hydra_engine_v20.load',return_value=(g,p)):
    status=public_status()
   self.assertTrue(status['available']);self.assertEqual(status['remaining'],11);self.assertNotIn('runtime',status)

class V20CleanupTicketTests(unittest.TestCase):
 def test_exhausted_ticket_can_still_finalize_but_not_admit(self):
  import tempfile,json,os,time
  from pathlib import Path
  from unittest.mock import patch
  from serve.hydra_engine_v20 import load,digest,available
  with tempfile.TemporaryDirectory() as tmp:
   g=Path(tmp)/'grant.json';s=Path(tmp)/'counter.json'
   g.write_text(json.dumps(dict(counter=str(s),expires_at=time.time()+30,protected={})))
   s.write_text(json.dumps(dict(state='ARMED',used=12,max_requests=12,grant_sha256=digest(g))))
   with patch.dict(os.environ,HYDRA_LAB_MODE='1',HYDRA_V20_GRANT=str(g)):
    self.assertFalse(available());self.assertEqual(load(require_active=False)[1],s)
 def test_uncertain_cleanup_halts_without_rearming(self):
  import tempfile,json
  from pathlib import Path
  from unittest.mock import patch
  from serve.hydra_engine_v20 import halt
  with tempfile.TemporaryDirectory() as tmp:
   s=Path(tmp)/'counter.json';s.write_text(json.dumps(dict(state='ARMED',used=1,max_requests=12)))
   with patch('serve.hydra_engine_v20.load',return_value=({},s)):halt('CLEANUP_UNCERTAIN','run')
   self.assertEqual(json.loads(s.read_text())['state'],'HALTED');self.assertEqual(json.loads(s.read_text())['used'],1)

class V20PrismLoaderTests(unittest.TestCase):
 def test_iocp_never_silently_falls_back_to_standard_prism(self):
  from serve.hydra_native_text_server import select_loader
  from pathlib import Path
  cat=dict(id='prism-ml/Ternary-Bonsai-2-27B-gguf',runtime_path='reference.exe')
  with self.assertRaises((ValueError,FileNotFoundError)):
   select_loader(cat,dict(model_io='iocp',mmap=False),False,Path('missing-prism-loader-manifest.json'))
 def test_standard_identity_is_preserved(self):
  from serve.hydra_native_text_server import select_loader
  cat=dict(id='prism-ml/Ternary-Bonsai-2-27B-gguf',runtime_path='reference.exe')
  self.assertEqual(select_loader(cat,dict(model_io='standard'),False),cat)

class V20NativePreparationTests(unittest.TestCase):
 def test_catalog_preparation_failure_does_not_leak_workspace_lock(self):
  import tempfile,threading
  from types import SimpleNamespace
  from pathlib import Path
  from unittest.mock import patch
  from serve.hydra_native_text_server import execute
  with tempfile.TemporaryDirectory() as tmp:
   workspace=SimpleNamespace(lock=threading.Lock(),store=SimpleNamespace(root=Path(tmp)),lab=SimpleNamespace(features=None),catalog=lambda:[])
   with patch('serve.hydra_lab_benchmarks.acquire_runtime_lock',return_value=object()):
    with self.assertRaises(StopIteration):execute(workspace,dict(profile='cpu',model_id='missing',prompt='x',thinking='off',max_tokens=1,samples=1))
   self.assertFalse(workspace.lock.locked())

class V20LoaderResolverTests(unittest.TestCase):
 def test_prism_legacy_raw_path_cannot_ignore_loader_on(self):
  import tempfile,json
  from pathlib import Path
  from serve.hydra_feature_control import FeatureControl,FeatureError
  catalog=json.loads(Path(__file__).with_name('hydra_lab_catalog.json').read_text(encoding='utf8'))
  with tempfile.TemporaryDirectory() as tmp:
   control=FeatureControl(Path(tmp),catalog=lambda:catalog,admission=lambda:{'state':'RELEASED'})
   old=control.export()
   # Identify the existing loader category from its stable feature number.
   loader=next(k for k in old['features'] if k.endswith('-029'));mmap=next(k for k in old['features'] if k.endswith('-028'))
   changes={loader:dict(desired=True),mmap:dict(desired=False),'adapter.prism-ml/Ternary-Bonsai-2-27B-gguf':dict(desired=True)}
   plan=control.preview(changes,include_dependencies=True,include_dependents=True);control.apply(dict(expected_version=old['version'],changes=plan['changes'],allow_blocked=True,source='v20 contract'))
   with self.assertRaisesRegex(FeatureError,'NATIVE_TEMPLATE_SERVER_REQUIRED'):
    control.resolve(dict(profile='cpu',model_id='prism-ml/Ternary-Bonsai-2-27B-gguf',prompt='x',prompt_id='raw',max_tokens=1,samples=1))

class V20LoaderTelemetryTests(unittest.TestCase):
 def test_header_only_iocp_cannot_claim_tensor_loading(self):
  from serve.hydra_native_text_server import loader_telemetry
  with self.assertRaises(ValueError):loader_telemetry('HYDRA_LOADER mode=iocp consumer=llama_file::read_raw\nHYDRA_IOCP consumer_bytes=64 physical_bytes=4096 completions=1 cleanup=closed',100000000)
 def test_actual_consumer_and_physical_bytes_stay_distinct(self):
  from serve.hydra_native_text_server import loader_telemetry
  x=loader_telemetry('HYDRA_LOADER mode=iocp consumer=llama_file::read_raw\nHYDRA_IOCP consumer_bytes=100000000 physical_bytes=100003840 completions=96 cleanup=closed',100000000)
  self.assertEqual(x['consumer_bytes'],100000000);self.assertEqual(x['physical_bytes'],100003840);self.assertEqual(x['completions'],96)

class V20ExactTensorTelemetryTests(unittest.TestCase):
 def test_partial_tensor_bytes_are_rejected_without_slack(self):
  from serve.hydra_native_text_server import loader_telemetry
  with self.assertRaises(ValueError):loader_telemetry('HYDRA_LOADER mode=iocp consumer=llama_file::read_raw\nHYDRA_IOCP consumer_bytes=99500000 physical_bytes=100003840 completions=96 cleanup=closed',100000000)

class V20RepositoryBridgeTests(unittest.TestCase):
 def test_native_retrieval_enters_shared_repository_context_and_node_budget(self):
  from unittest.mock import Mock,patch
  from types import SimpleNamespace
  from contextlib import contextmanager
  from serve.hydra_native_text_server import retrieve_context
  nodes=[dict(content='x',source='doc',source_sha256='a',id=str(i),evidence='source') for i in (1,2)]
  lab=SimpleNamespace(features=SimpleNamespace(setting=lambda n:dict(desired=False,parameters={'max_nodes':1})),retrieve=Mock(return_value=dict(nodes=nodes)),g=SimpleNamespace(roots=[],path='fixture.sqlite'),graphify_index=None)
  @contextmanager
  def bridge(*args,**kwargs):yield dict(selected_sources=1)
  with patch('serve.hydra_graphify_runtime.repository_context',side_effect=bridge) as context:
   _,trace=retrieve_context(lab,dict(prompt='query',graph=True))
  context.assert_called_once();self.assertEqual(len(trace['nodes']),1);self.assertEqual(trace['graphify']['selected_sources'],1)
 def test_graph_off_releases_retained_repository_index(self):
  from unittest.mock import Mock
  from types import SimpleNamespace
  from serve.hydra_native_text_server import retrieve_context
  index=Mock();lab=SimpleNamespace(graphify_index=index)
  retrieve_context(lab,dict(prompt='x'));index.clear.assert_called_once()
 def test_close_releases_retained_repository_index(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import Mock
  from serve.hydra_lab_app import Lab
  with tempfile.TemporaryDirectory() as tmp:
   lab=object.__new__(Lab);lab.benchmarks=Mock();lab.stop_backend=Mock();lab.data=Path(tmp);lab.calls=[];lab.graphify_index=Mock()
   lab.close();lab.graphify_index.clear.assert_called_once()

class V20NativeSourceFreshnessTests(unittest.TestCase):
 def test_changed_source_after_loading_cannot_reach_generation(self):
  import tempfile,time
  from pathlib import Path
  from serve.hydra_graph_memory import GraphMemory
  from serve.hydra_native_text_server import verify_native_sources
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'source.txt';source.write_text('codice47');g=GraphMemory.create(root/'g.sqlite',roots=[root]);g.ingest('lab',source)
   nodes=g.retrieve('lab','codice47',allowed_sources=[str(source)],deadline=time.monotonic()+2)
   trace=dict(nodes=nodes,database=str(g.path),authorized_source_roots=[str(root)])
   self.assertTrue(verify_native_sources(trace,'codice47'))
   source.write_text('codice48')
   with self.assertRaises(ValueError):verify_native_sources(trace,'codice47')

class V20RepositoryShutdownTests(unittest.TestCase):
 def test_workers_stop_before_index_memory_is_released(self):
  import tempfile
  from pathlib import Path
  from unittest.mock import Mock
  from serve.hydra_lab_app import Lab
  with tempfile.TemporaryDirectory() as tmp:
   order=[];lab=object.__new__(Lab);lab.benchmarks=Mock();lab.benchmarks.shutdown.side_effect=lambda:order.append('shutdown');lab.graphify_index=Mock();lab.graphify_index.clear.side_effect=lambda:order.append('clear');lab.stop_backend=Mock();lab.data=Path(tmp);lab.calls=[]
   lab.close();self.assertEqual(order,['shutdown','clear'])

class V20NativeContextBudgetTests(unittest.TestCase):
 def test_repository_uses_bounded_whole_paragraph_groups_for_native_model(self):
  from unittest.mock import Mock,patch
  from types import SimpleNamespace
  from contextlib import contextmanager
  from serve.hydra_native_text_server import retrieve_context
  lab=SimpleNamespace(features=SimpleNamespace(setting=lambda n:dict(desired=False,parameters={'max_nodes':1})),retrieve=Mock(return_value=dict(nodes=[])),g=SimpleNamespace(roots=[],path='fixture.sqlite'),graphify_index=None)
  @contextmanager
  def bridge(*args,**kwargs):yield {}
  with patch('serve.hydra_graphify_runtime.repository_context',side_effect=bridge) as context:retrieve_context(lab,dict(prompt='query',graph=True))
  self.assertEqual(context.call_args.kwargs.get('section_chars'),384)
 def test_other_native_defaults_stay_512_but_explicit_context_applies(self):
  from serve.hydra_native_text_server import native_options
  from types import SimpleNamespace
  settings={9:dict(desired=False,parameters={}),11:dict(desired=False,parameters={}),6:dict(desired=False),28:dict(desired=True),29:dict(desired=False,parameters={})}
  control=SimpleNamespace(setting=lambda n:settings[n])
  self.assertEqual(native_options(control,'other')['context'],512)
  settings[11]=dict(desired=True,parameters=dict(context=1024,max_tokens=64,seed=7))
  self.assertEqual(native_options(control,'other')['context'],1024)

class V20NativeComparisonTests(unittest.TestCase):
 def test_comparison_binds_actual_context_and_native_parameters(self):
  import copy
  from serve.hydra_native_text_server import bind_native_comparison
  row=dict(model_hash='model',runtime_hash='runtime',prompt_hash='question',quantization='PTQ1_0',template_hash='template',parameters={},configuration=dict(context=512,threads=2,mmap=True),request_json=dict(samples=1),applied_messages=[dict(role='user',content='source47')])
  a=copy.deepcopy(row);b=copy.deepcopy(row);bind_native_comparison(a);b['applied_messages'][0]['content']='source48';bind_native_comparison(b)
  self.assertNotEqual(a['comparison_key'],b['comparison_key']);self.assertEqual(a['parameters']['messages'],a['applied_messages'])
  b=copy.deepcopy(row);b['configuration']['context']=1024;bind_native_comparison(b);self.assertNotEqual(a['comparison_key'],b['comparison_key'])

class V20QueuedIdentityTests(unittest.TestCase):
 def test_queued_bonsai_format_comes_from_catalog_without_starting_runtime(self):
  import tempfile,threading
  from pathlib import Path
  from types import SimpleNamespace
  from unittest.mock import Mock,patch
  from serve.hydra_lab_benchmarks import Workspace
  with tempfile.TemporaryDirectory() as tmp:
   workspace=object.__new__(Workspace);workspace.jobs_lock=threading.Lock();workspace.lock=threading.Lock();workspace.jobs={};workspace.store=SimpleNamespace(root=Path(tmp),put=Mock());workspace.catalog_path=Path(__file__).with_name('hydra_lab_catalog.json')
   with patch('serve.hydra_lab_benchmarks.threading.Thread') as thread:
    row=workspace.submit(dict(profile='cpu',model_id='prism-ml/Ternary-Bonsai-2-27B-gguf',prompt='x',prompt_id='queue-format',samples=1,max_tokens=1,thinking='off'))
   self.assertEqual(row['status'],'QUEUED');self.assertEqual(row['quantization'],'PTQ1_0');self.assertEqual(row['backend'],'NOT_VERIFIED')
