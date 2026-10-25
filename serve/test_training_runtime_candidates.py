import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

class TrainingCandidateTests(unittest.TestCase):
 def test_cpu_proof_does_not_select_gpu_and_source_drift_is_rejected(self):
  from serve import training_runtime_candidates as c
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True)
   python=folder/'python.exe';python.write_bytes(b'fixture')
   workflow=folder/'proof/workflow.json';workflow.parent.mkdir();workflow.write_text('{}')
   proof=dict(passed=True,runner='trl_cpu',device='cpu',runtime_sha256=c.fingerprint(root,'trl_cpu'),python_sha256=hashlib.sha256(python.read_bytes()).hexdigest(),environment_sha256='environment',report=str(workflow),report_sha256=hashlib.sha256(workflow.read_bytes()).hexdigest())
   manifest=dict(python=str(python),dependency_health={'state':'healthy'},training_validation={'trl_cpu:cpu':proof})
   (folder/'environment-manifest.json').write_text(json.dumps(manifest))
   with patch.object(c,'environment_fingerprint',return_value='environment'):
    self.assertEqual(c.activate(root,folder,Path('original'),'trl_cpu','cpu'),python)
    self.assertEqual(c.selected_python(root,Path('gpu-original'),'trl_cpu','cuda'),Path('gpu-original'))
    self.assertEqual(c.activate(root,None,Path('original'),'trl_cpu','cpu',rollback=True),Path('original'))
    self.assertEqual(c.activate(root,None,Path('original'),'trl_cpu','cpu',rollback=True),python)
    workflow.write_text('{"changed":true}')
    with self.assertRaisesRegex(ValueError,'proof'):c.selected_python(root,Path('original'),'trl_cpu','cpu')
 def test_failed_validation_invalidates_only_requested_scope(self):
  from serve import training_runtime_candidates as c
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True)
   path=folder/'environment-manifest.json';path.write_text(json.dumps({'training_validation':{'trl_cpu:cpu':{'passed':True},'unsloth_qlora:cuda':{'passed':True}}}))
   with self.assertRaises((ValueError,KeyError)):c.validate(root,folder)
   self.assertNotIn('trl_cpu:cpu',json.loads(path.read_text())['training_validation'])
   self.assertIn('unsloth_qlora:cuda',json.loads(path.read_text())['training_validation'])
 def test_inference_proof_is_not_training_proof(self):
  from serve import training_runtime_candidates as c
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True)
   python=folder/'python.exe';python.write_bytes(b'fixture')
   (folder/'environment-manifest.json').write_text(json.dumps(dict(python=str(python),dependency_health={'state':'healthy'},inference_validation={'passed':True})))
   with self.assertRaises(ValueError):c.activate(root,folder,Path('original'),'trl_cpu','cpu')

if __name__=='__main__':unittest.main()
