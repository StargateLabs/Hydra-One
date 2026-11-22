import json,tempfile,unittest
from pathlib import Path
from serve.llama_gpu_update import proof,selected_binary,digest,rollback

class GPUSelectionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.folder=self.root/'output/updates/candidates/gpu';self.folder.mkdir(parents=True)
  binary=self.folder/'llama-server.exe';binary.write_bytes(b'fixture binary')
  self.candidate=dict(candidate_directory=str(self.folder),sha256='1'*64,source='https://github.com/unslothai/llama.cpp/releases/download/b11541-mix-2500203/app-windows-x64-rocm-gfx110X.zip',files=[dict(path='llama-server.exe',bytes=binary.stat().st_size,sha256=digest(binary))])
  self.report=dict(passed=True,gpu_offload_confirmed=True,owned_process_stopped=True,original_preserved=True,state={'gpu_requested':True},candidate=str(self.folder),archive_sha256='1'*64,version='b11541-mix-2500203')
  self.path=self.root/'output/verification/llama-b11541-gpu-real.json';self.path.parent.mkdir();self.save()
 def save(self):self.path.write_text(json.dumps(self.report),encoding='utf-8')
 def test_candidate_scoped_proof_supports_next_release(self):
  version='b99999-mix-2500203'
  self.candidate['source']=self.candidate['source'].replace('b11541-mix-2500203',version)
  self.report['version']=version
  (self.folder/'GPU-validation.json').write_text(json.dumps(self.report),encoding='utf-8')
  self.path.unlink()
  self.assertEqual(proof(self.root,self.candidate,verify=True)['version'],version)
 def test_failed_scoped_proof_does_not_fall_back_to_old_success(self):
  bad={**self.report,'passed':False}
  (self.folder/'GPU-validation.json').write_text(json.dumps(bad),encoding='utf-8')
  with self.assertRaisesRegex(ValueError,'validation'):proof(self.root,self.candidate)
 def test_cpu_proof_cannot_select_gpu(self):
  self.report['state']['gpu_requested']=False;self.save()
  with self.assertRaisesRegex(ValueError,'validation'):proof(self.root,self.candidate)
 def test_other_archive_cannot_reuse_gpu_proof(self):
  self.candidate['sha256']='2'*64
  with self.assertRaisesRegex(ValueError,'another'):proof(self.root,self.candidate)
 def test_modified_binary_is_rejected(self):
  (self.folder/'llama-server.exe').write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'changed'):proof(self.root,self.candidate,verify=True)
 def test_gpu_rollback_keeps_cpu_registry_and_files(self):
  (self.root/'data').mkdir();cpu=self.root/'data/runtime-selection.json';cpu.write_text('{"active":{"scope":"llama_cpu"}}')
  registry=self.root/'data/runtime-gpu-selection.json';registry.write_text(json.dumps({'active':proof(self.root,self.candidate,verify=True),'previous':None}))
  self.assertEqual(selected_binary(self.root),self.folder/'llama-server.exe')
  original=cpu.read_bytes();rollback(self.root)
  self.assertIsNone(selected_binary(self.root));self.assertEqual(cpu.read_bytes(),original);self.assertTrue((self.folder/'llama-server.exe').exists())

 def test_selected_runtime_keeps_its_proof_when_next_candidate_is_tested(self):
  (self.root/'data').mkdir();active=proof(self.root,self.candidate,verify=True)
  (self.root/'data/runtime-gpu-selection.json').write_text(json.dumps({'active':active}))
  self.report['passed']=False;self.save()
  self.assertEqual(selected_binary(self.root),self.folder/'llama-server.exe')
