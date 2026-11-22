import hashlib,json,tempfile,unittest
from pathlib import Path
from serve.soup_runtime import selected_package,rollback_package
class SoupSelectionTests(unittest.TestCase):
 def setup_candidate(self,root):
  bridge=root/'tools/train_soup_candidate.py';bridge.parent.mkdir();bridge.write_text('verified bridge')
  package=root/'output/updates/soup-candidates/test/packages';(package/'soup_cli').mkdir(parents=True);source=package/'soup_cli/module.py';source.write_text('original')
  active={'version':'0.75.2','package_root':str(package),'validation':{'cpu_verified':True,'gpu_verified':True,'bridge_sha256':hashlib.sha256(bridge.read_bytes()).hexdigest()},'files':[{'path':'soup_cli/module.py','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}]}
  registry=root/'data/soup-package-selection.json';registry.parent.mkdir();registry.write_text(json.dumps({'active':active,'previous':None}));return source,bridge
 def test_changed_package_is_rejected_and_rollback_preserves_files(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source,bridge=self.setup_candidate(root)
   self.assertEqual(selected_package(root,verify=True)['version'],'0.75.2')
   source.write_text('changed')
   with self.assertRaisesRegex(ValueError,'package changed'):selected_package(root,verify=True)
   source.write_text('original');rollback_package(root)
   self.assertIsNone(selected_package(root));self.assertEqual(source.read_text(),'original')
 def test_bridge_change_requires_revalidation(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source,bridge=self.setup_candidate(root);bridge.write_text('new bridge')
   with self.assertRaisesRegex(ValueError,'validation'):selected_package(root)
 def test_new_version_uses_its_own_bridge_and_keeps_old_bridge(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source,old=self.setup_candidate(root)
   current=old.with_name('train_soup_candidate_0760.py');current.write_text('new verified bridge')
   registry=root/'data/soup-package-selection.json';saved=json.loads(registry.read_text())
   saved['active']['version']='0.76.0';saved['active']['validation']['bridge_sha256']=hashlib.sha256(current.read_bytes()).hexdigest();registry.write_text(json.dumps(saved))
   self.assertEqual(selected_package(root,verify=True)['version'],'0.76.0')
   old.write_text('old runtime remains separate')
   self.assertEqual(selected_package(root)['version'],'0.76.0')
   current.write_text('changed new bridge')
   with self.assertRaisesRegex(ValueError,'validation'):selected_package(root)
