import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve.model_engine_requirements import requirement,assert_optional_engine
class ModelEngineRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.root=Path(self.folder.name)
        self.model=self.root/'native.gguf';self.model.write_bytes(b'GGUF'+b'0'*32)
        (self.root/'strata-native.json').write_text(json.dumps({'exe':'strata.exe','cwd':str(self.root),'args':['--native',str(self.model),'--pack',str(self.root/'pack')]}))
    def test_registered_native_model_requires_strata_even_if_pack_not_ready(self):
        info=requirement(self.root,self.model);self.assertEqual(info['required_engine'],'strata');self.assertEqual(info['strata_key'],'native');self.assertFalse(info['strata_ready'])
    def test_other_gguf_in_same_directory_is_not_assumed_native(self):
        self.assertEqual(requirement(self.root,self.root/'ordinary.gguf')['required_engine'],'gguf')
    def test_native_model_is_rejected_before_optional_engine_start(self):
        from serve.optional_backends import OptionalBackends
        manager=OptionalBackends.__new__(OptionalBackends);manager.root=self.root
        with patch('serve.optional_backends.subprocess.Popen') as worker:
            with self.assertRaisesRegex(ValueError,'Strata'):manager.start({'mode':'gguf','model_path':str(self.model)},operational_idle=True)
            worker.assert_not_called()
    def test_native_model_cannot_receive_llama_cpu_gpu_fit(self):
        from serve.optional_backends import OptionalBackends
        manager=OptionalBackends.__new__(OptionalBackends);manager.root=self.root
        with self.assertRaisesRegex(ValueError,'Strata'):manager.fit_model({'mode':'gguf','model_path':str(self.model)})
    def test_python_model_is_not_blocked_by_native_gguf_requirement(self):
        assert_optional_engine(self.root,{'mode':'safetensors','model_path':str(self.model)})
if __name__=='__main__':unittest.main()
