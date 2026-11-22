import tempfile,threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from serve.optional_catalogue import OptionalCatalogue
class LocalRemovalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.models=self.root/'models';self.models.mkdir();self.path=self.models/'test.gguf';self.path.write_bytes(b'GGUF-test')
  self.state={'status':'idle','local_models':[{'name':'test','path':str(self.path),'bytes':9}]}
  manager=SimpleNamespace(root=self.root,binary=self.root/'llama.exe',lock=threading.RLock(),models_roots=[self.models],model_cache_at=1,status=lambda:self.state)
  self.catalogue=OptionalCatalogue(manager)
 def test_registered_file_removed_and_cache_invalidated(self):
  self.assertTrue(self.catalogue.delete_local(str(self.path))['removed']);self.assertFalse(self.path.exists());self.assertEqual(self.catalogue.manager.model_cache_at,0)
 def test_active_model_and_training_protected(self):
  self.state.update(status='ready',model_path=str(self.path))
  with self.assertRaises(ValueError):self.catalogue.delete_local(str(self.path))
  self.state['status']='idle'
  with self.assertRaises(ValueError):self.catalogue.delete_local(str(self.path),training_model=str(self.path))
  self.assertTrue(self.path.exists())
 def test_unregistered_and_outside_paths_refused(self):
  with self.assertRaises(ValueError):self.catalogue.delete_local(str(self.root/'other.gguf'))
  outside=self.root/'outside.gguf';outside.write_bytes(b'keep');self.state['local_models']=[{'path':str(outside)}]
  with self.assertRaises(ValueError):self.catalogue.delete_local(str(outside))
  self.assertEqual(outside.read_bytes(),b'keep')
 def test_model_directory_only(self):
  folder=self.models/'native';folder.mkdir();(folder/'config.json').write_text('{}');(folder/'model.safetensors').write_bytes(b'test');self.state['local_models']=[{'path':str(folder)}]
  self.catalogue.delete_local(str(folder));self.assertFalse(folder.exists())
if __name__=='__main__':unittest.main()
