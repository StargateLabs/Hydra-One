"""v11 integration regression; pure tests, no models or GPU."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from serve import hydra_execution_v10 as admission
class JobIdentityTests(unittest.TestCase):
 def test_empty_owned_job_is_not_overruled_by_reused_numeric_ppid(self):
  lease=admission.Reservation.__new__(admission.Reservation)
  lease.row={'children':[{'pid':12345,'created':0}],'spawn_uncertain':False,'state':'CLEANUP'}
  lease.job_members=lambda:[];lease.transition=lambda state:lease.row.update(state=state)
  with patch.object(admission,'alive',return_value=False),patch.object(admission.psutil,'process_iter',return_value=[SimpleNamespace(info={'ppid':12345})]):
   lease.verify_cleanup()
  self.assertEqual(lease.row['state'],'VERIFIED_TERMINAL')
class FunctionalContractTests(unittest.TestCase):
 def test_valid_request_keeps_original_payload(self):
  from serve.hydra_lab_functional import validate
  body={'path':'/lab/chat','request':{'messages':[{'role':'user','content':'  Ciao\n'}],'max_tokens':8}}
  self.assertIs(validate(body)['request'],body['request'])
 def test_unknown_route_is_rejected(self):
  from serve.hydra_lab_functional import validate
  with self.assertRaises(ValueError):validate({'path':'/v1/systemone','request':{}})

class BundleIntegrationTests(unittest.TestCase):
 def test_bundle_package_preserved_while_new_lab_modules_are_resolved(self):
  from serve.hydra_one import runtime
  pending=runtime()[4]
  import hydra_lab.adapters as adapters
  from serve.hydra_lab_modules import load
  graph=load('graph_hybrid');scorer=load('decision_scoring')
  self.assertIs(adapters.Pending,pending)
  self.assertTrue(str(graph.__file__).endswith('hydra_lab\\graph_hybrid.py'))
  self.assertTrue(hasattr(scorer,'NativeCPUBackend'))

class RedirectorOwnershipTests(unittest.TestCase):
 def test_verified_python_redirector_descendant_is_admitted(self):
  import tempfile,pathlib,json
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);(root/'lease.json').write_text(json.dumps({'run_id':'fixture','state':'RUNNING','expected_command':['python','--dense-worker'],'owner':{'pid':9,'created':1},'children':[{'pid':111,'created':10}]}))
   parent=SimpleNamespace(pid=111,create_time=lambda:10)
   with patch.object(admission,'ROOT',root),patch.object(admission,'identity',return_value={'pid':222,'created':20}),patch.object(admission,'alive',return_value=True),patch.object(admission.psutil,'Process',return_value=SimpleNamespace(parents=lambda:[parent])):
    admission.require_child_admission()

class BuildAdmissionTests(unittest.TestCase):
 def test_compile_only_rocm_path_is_not_gpu_inference(self):
  import threading
  lease=admission.Reservation.__new__(admission.Reservation);lease.thread=threading.get_ident();lease.handle=1;lease.job=2;lease.memory_lease=None;lease.request={'backend':'BUILD_ONLY'};lease.children=[];lease.row={'children':[],'request':{}};lease.transition=lambda state:None;lease.k=SimpleNamespace(AssignProcessToJobObject=lambda *args:True)
  child=SimpleNamespace(pid=333,_handle=44)
  lease.path=admission.ROOT/'lease.json'
  with patch.object(admission.Path,'exists',return_value=True),patch.object(admission.subprocess,'Popen',return_value=child),patch.object(admission,'identity',return_value={'pid':333,'created':1}),patch.object(admission.psutil,'Process',return_value=SimpleNamespace(resume=lambda:None)):
   self.assertIs(lease.spawn(['cmd.exe','/d','/c','compile-rocm-only.cmd']),child)

class FunctionalAdmissionTests(unittest.TestCase):
 def test_busy_functional_request_uses_coordinator_and_http409(self):
  import tempfile,pathlib,io,json
  from serve.hydra_lab_app import handler
  with tempfile.TemporaryDirectory() as d:
   lab=SimpleNamespace(data=pathlib.Path(d),benchmarks=SimpleNamespace(lock=SimpleNamespace(locked=lambda:True),record_application_run=lambda *a:'wrong-path'))
   for name in ('ingest','retrieve','chat','score','unavailable'):setattr(lab,name,lambda *args:None)
   for name in ('assess','execute','submit','cancel'):setattr(lab.benchmarks,name,lambda *args:None)
   obj=handler(lab,'key').__new__(handler(lab,'key'));obj.headers={'X-Hydra-Lab':'key','Content-Length':'2'};obj.path='/lab/chat';obj.rfile=io.BytesIO(b'{}');answers=[];obj.reply=lambda code,value,*args:answers.append((code,value))
   with patch('serve.hydra_lab_functional.execute',return_value={'run_id':'busy','status':'BLOCKED_BUSY','error':'occupied'}) as execute:obj.do_POST()
   self.assertEqual(answers[0][0],409);execute.assert_called_once()
 def test_coordinator_and_record_share_the_same_run_id(self):
  @admission.exclusive_execute
  def endpoint(workspace,body,_key=None):return {'run_id':_key,'cleanup':True}
  fake=SimpleNamespace(row={'memory_policy':{'kind':'SOFTWARE_FIXTURE_ONLY'},'request':{},'children':[]},acquire=lambda:None,verify_cleanup=lambda:None,release=lambda **kw:None,transition=lambda *a:None)
  ws=SimpleNamespace(store=SimpleNamespace(put=lambda row:None,get=lambda key:True))
  with patch.object(admission._local,'reservation',None,create=True),patch.object(admission,'Reservation',return_value=fake):
   row=endpoint(ws,{'profile':'cpu'})
  self.assertIsNotNone(row['run_id'])
  self.assertEqual(row['process_memory_policy']['kind'],'SOFTWARE_FIXTURE_ONLY')

class CatalogMeaningTests(unittest.TestCase):
 def test_retrieval_success_is_not_model_inference_evidence(self):
  from serve.hydra_lab_benchmarks import catalog_evidence
  entry={'id':'local/Qwen3-0.6B-Q8_0','status':'CATALOGED'}
  row={'run_id':'graph-only','model':entry['id'],'origin':'E2E_TEST','status':'PASS','parameters':{'functional_path':'/lab/retrieve'}}
  self.assertEqual(catalog_evidence(entry,[row])['status'],'CATALOGED')

class AdmissionFailureRecoveryTests(unittest.TestCase):
 def test_rejected_gpu_without_children_is_persisted_and_releases(self):
  import tempfile,pathlib,threading
  from unittest.mock import Mock
  @admission.exclusive_execute
  def endpoint(ws,body,_key=None):raise ValueError('GPU experiments suspended after native ErrorDeviceLost')
  with tempfile.TemporaryDirectory() as d:
   rows={};store=SimpleNamespace(root=pathlib.Path(d),put=lambda row:rows.update({row['run_id']:row}),get=lambda key:rows[key]);ws=SimpleNamespace(store=store,lock=threading.Lock())
   fake=SimpleNamespace(acquire=Mock(),verify_cleanup=Mock(),release=Mock(),transition=Mock())
   with patch.object(admission._local,'reservation',None,create=True),patch.object(admission,'Reservation',return_value=fake):row=endpoint(ws,{'profile':'v8-qwen-full','model_id':'local/Qwen3-0.6B-Q8_0'})
   self.assertEqual(row['status'],'BLOCKED_GPU_QUARANTINE');fake.release.assert_called_once()
