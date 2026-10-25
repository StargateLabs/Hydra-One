import hashlib,json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from serve.python_inference_update import selected_python,activate,fingerprint,validate
class CandidateSelectionTests(unittest.TestCase):
 @patch('serve.python_inference_update.environment_fingerprint',return_value='fixture')
 def test_cpu_candidate_does_not_replace_gpu_runtime(self,inventory):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'serve').mkdir();(root/'serve/safetensors_runtime.py').write_text('fixture')
   folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True);python=folder/'python.exe';python.write_bytes(b'fixture')
   proof={'passed':True,'environment_sha256':'fixture','runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest()}
   (folder/'environment-manifest.json').write_text(json.dumps({'python':str(python),'dependency_health':{'state':'healthy'},'inference_validation':proof}))
   original=Path('original');activate(root,folder,original)
   self.assertEqual(selected_python(root,original,gpu=True),original)
   self.assertEqual(selected_python(root,original),python)
 @patch('serve.python_inference_update.environment_fingerprint',return_value='fixture')
 def test_vendor_candidate_requires_both_real_device_proofs(self,inventory):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);(root/'serve').mkdir();(root/'serve/safetensors_runtime.py').write_text('fixture')
   folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True);python=folder/'python.exe';python.write_bytes(b'fixture')
   proof={'passed':True,'environment_sha256':'fixture','runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest()}
   (folder/'environment-manifest.json').write_text(json.dumps({'python':str(python),'vendor_copy':True,'dependency_health':{'state':'healthy'},'inference_validation':proof}))
   with self.assertRaisesRegex(ValueError,'CPU and GPU'):activate(root,folder,Path('original'))
   self.assertFalse((root/'data/inference-python-selection.json').exists())
 def test_default_is_preserved_without_registry(self):
  with tempfile.TemporaryDirectory() as d:self.assertEqual(selected_python(Path(d),Path('original')),Path('original'))
 def test_unvalidated_candidate_cannot_replace_runtime(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True)
   (folder/'environment-manifest.json').write_text(json.dumps({'python':'outside','dependency_health':{'state':'healthy'}}))
   with self.assertRaises(ValueError):activate(root,folder,Path('original'))
   self.assertFalse((root/'data/inference-python-selection.json').exists())
 def test_outside_candidate_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):activate(Path(d),Path(d)/'other',Path('original'))

 @patch('serve.python_inference_update.environment_fingerprint',return_value='fixture')
 def test_forward_rollback_and_source_drift(self,inventory):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'serve').mkdir();(root/'serve/safetensors_runtime.py').write_text('fixture runtime')
   folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True);python=folder/'python.exe';python.write_bytes(b'fixture executable')
   proof={'passed':True,'environment_sha256':'fixture','runtime_sha256':fingerprint(root),'python_sha256':hashlib.sha256(python.read_bytes()).hexdigest()}
   (folder/'environment-manifest.json').write_text(json.dumps({'python':str(python),'dependency_health':{'state':'healthy'},'inference_validation':proof}))
   original=Path('original');self.assertEqual(activate(root,folder,original),python)
   self.assertEqual(activate(root,None,original,rollback=True),original)
   self.assertEqual(activate(root,None,original,rollback=True),python)
   (root/'serve/safetensors_runtime.py').write_text('changed runtime')
   with self.assertRaises(ValueError):selected_python(root,original)

 def test_vision_helper_change_invalidates_runtime_proof(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'serve').mkdir();(root/'serve/safetensors_runtime.py').write_text('runtime');helper=root/'serve/transformers_vision.py';helper.write_text('v1');before=fingerprint(root);helper.write_text('v2');self.assertNotEqual(before,fingerprint(root))

 def test_failed_revalidation_removes_previous_proof(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'output/updates/python-plans/test';folder.mkdir(parents=True);python=folder/'python.exe';python.write_bytes(b'fixture')
   report=folder/'environment-manifest.json';report.write_text(json.dumps({'python':str(python),'dependency_health':{'state':'healthy'},'inference_validation':{'passed':True}}))
   with self.assertRaises(ValueError):validate(root,folder)
   self.assertNotIn('inference_validation',json.loads(report.read_text()))
