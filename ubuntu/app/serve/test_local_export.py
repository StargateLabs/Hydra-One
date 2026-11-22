import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from serve.local_export import LocalExport

class ExportTests(unittest.TestCase):
    def make(self,root,code,report):
        manager=SimpleNamespace(root=Path(root),model_cache_at=5)
        engine=LocalExport(manager);folder=Path(root)/'output/model-exports/test';folder.mkdir(parents=True)
        output=folder/'model.gguf';output.write_bytes(b'GGUF')
        output.with_suffix('.export.json').write_text(json.dumps(report),encoding='utf-8')
        engine.state=dict(status='running',output=str(output),started_at=0);engine.process=Mock();engine.process.poll.return_value=code;engine.process.returncode=code;engine.lease=Mock()
        return engine
    def test_nonzero_or_invalid_export_never_succeeds(self):
        for code,report in [(1,{'status':'complete'}),(0,{}),(0,{'status':'complete','bytes':4,'sha256':'fake'}),(0,{'status':'complete','bytes':8,'sha256':'a'*64})]:
            with self.subTest(code=code),tempfile.TemporaryDirectory() as root:
                engine=self.make(root,code,report);lease=engine.lease
                self.assertEqual(engine.status()['status'],'failed');lease.release.assert_called_once()
    def test_completion_persisted_and_partial_cleaned(self):
        with tempfile.TemporaryDirectory() as root:
            engine=self.make(root,0,{'status':'complete','bytes':4,'sha256':'a'*64})
            partial=Path(engine.state['output']).parent/'owned.partial.gguf';partial.touch()
            self.assertEqual(engine.status()['status'],'complete');self.assertFalse(partial.exists())
            self.assertEqual(LocalExport(engine.manager).status()['status'],'complete')
            self.assertEqual(engine.manager.model_cache_at,0)
    def test_active_inference_rejected_before_conversion(self):
        with tempfile.TemporaryDirectory() as root:
            manager=SimpleNamespace(root=Path(root),status=lambda:{'status':'ready'})
            with self.assertRaises(ValueError):LocalExport(manager).start({},True)
