import json,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.local_model_discovery import LocalModelDiscovery

class DiscoveryCache(unittest.TestCase):
 def test_recent_cache_restores_existing_absolute_directories_without_scan(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder); model=root/'models';model.mkdir();(root/'data').mkdir()
   (root/'data/local-model-discovery.json').write_text(json.dumps(dict(finished_at=time.time(),directories=[str(model),'relative',str(root/'missing')],state={'found_directories':1})),encoding='utf-8')
   manager=SimpleNamespace(root=root,models_roots=[],lock=threading.RLock(),model_cache_at=0)
   with patch('serve.local_model_discovery.threading.Thread') as worker:
    discovery=LocalModelDiscovery(manager)
   worker.assert_not_called();self.assertEqual(manager.models_roots,[model]);self.assertTrue(discovery.state['cached'])
 def test_expired_cache_starts_background_scan(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'data').mkdir()
   (root/'data/local-model-discovery.json').write_text(json.dumps(dict(finished_at=time.time()-90000,directories=[],state={})),encoding='utf-8')
   manager=SimpleNamespace(root=root,models_roots=[],lock=threading.RLock(),model_cache_at=0)
   with patch('serve.local_model_discovery.threading.Thread') as worker:LocalModelDiscovery(manager)
   worker.return_value.start.assert_called_once()
 def test_rescan_is_single_background_worker_and_invalidates_inventory(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);manager=SimpleNamespace(root=root,models_roots=[],lock=threading.RLock(),model_cache_at=123)
   with patch('serve.local_model_discovery.threading.Thread') as worker:
    discovery=LocalModelDiscovery(manager)
    worker.return_value.is_alive.return_value=True
    first=discovery.rescan();discovery.rescan()
    worker.assert_called_once();worker.return_value.start.assert_called_once()
    self.assertEqual(first['status'],'scanning');self.assertEqual(manager.model_cache_at,0)
    worker.return_value.is_alive.return_value=False
    discovery.rescan();self.assertEqual(worker.call_count,2)
 def test_scan_failure_is_reported_instead_of_scanning_forever(self):
  with tempfile.TemporaryDirectory() as folder:
   manager=SimpleNamespace(root=Path(folder),models_roots=[],lock=threading.RLock(),model_cache_at=0)
   with patch('serve.local_model_discovery.threading.Thread'):discovery=LocalModelDiscovery(manager)
   with patch.object(discovery,'run',side_effect=OSError('disk unavailable')):discovery._scan_worker()
   self.assertEqual(discovery.state['status'],'error');self.assertEqual(discovery.state['error'],'disk unavailable')

 def test_scan_registers_metadata_without_reading_weights_and_persists_index(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);model=root/'model';model.mkdir()
   manager=SimpleNamespace(root=root,models_roots=[],lock=threading.RLock(),model_cache_at=123)
   with patch('serve.local_model_discovery.threading.Thread'):discovery=LocalModelDiscovery(manager)
   with patch('psutil.disk_partitions',return_value=[]),patch('serve.local_model_discovery.os.walk',return_value=iter([(str(model),[],['config.json','model.safetensors'])])),patch('serve.local_model_discovery.time.sleep'):
    discovery.run()
   self.assertEqual(manager.models_roots,[model]);self.assertEqual(manager.model_cache_at,0)
   saved=json.loads(discovery.cache.read_text(encoding='utf-8'));self.assertEqual(saved['directories'],[str(model)]);self.assertEqual(saved['state']['status'],'complete')

if __name__=='__main__':unittest.main()
