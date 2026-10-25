import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve.local_vision import projector,budget

class VisionTests(unittest.TestCase):
    def test_explicit_setting_and_projector_metadata_required(self):
        self.assertIsNone(projector({}))
        with self.assertRaises(ValueError):projector({'vision':'true'})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'projector.gguf';path.write_bytes(b'GGUF')
            with patch('serve.catalogue.read_gguf_header',return_value={'meta':{'general.architecture':'llama'}}):
                with self.assertRaises(ValueError):projector({'vision':True,'mmproj_path':str(path)})
            with patch('serve.catalogue.read_gguf_header',return_value={'meta':{'general.architecture':'clip','clip.has_vision_encoder':True}}):
                self.assertEqual(projector({'vision':True,'mmproj_path':str(path)}),path.resolve())
    def test_projector_memory_can_invalidate_fit(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'projector.gguf';path.write_bytes(b'GGUF')
            resources={'options':[{'context':4096,'fits':True,'ram_required_gib':1,'ram_estimated_upper_gib':1}]}
            with patch('serve.local_vision.projector',return_value=path),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=1024**3)):
                result=budget(resources,{})
                self.assertIsNone(result['recommended_context']);self.assertFalse(result['options'][0]['fits'])

    def test_gpu_requires_explicit_device_and_runtime_support(self):
        from serve.local_vision import device,runtime_arguments
        from types import SimpleNamespace
        self.assertEqual(device({}),'cpu')
        with self.assertRaises(ValueError):device({'vision_device':'gpu','gpu':False})
        with self.assertRaises(ValueError):device({'vision_device':'auto'})
        payload={'vision':True,'mmproj_path':'p.gguf','vision_device':'gpu','gpu':True}
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='--mmproj-offload',stderr='')):
            self.assertEqual(runtime_arguments(payload,Path('server.exe'))[-1],'--mmproj-offload')
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')):
            with self.assertRaises(ValueError):runtime_arguments(payload,Path('server.exe'))
        self.assertEqual(runtime_arguments({'vision':True,'mmproj_path':'p.gguf'},Path('server.exe'))[-1],'--no-mmproj-offload')

    def test_gpu_projector_memory_is_not_hidden(self):
        from types import SimpleNamespace
        row={'context':1024,'fits':True,'ram_required_gib':1,'ram_estimated_upper_gib':1,'gpu_required_gib':1,'gpu_estimated_alloc_gib':1}
        resources={'options':[row],'gpu_free_gib':1,'gpu_budget_gib':1}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'projector.gguf';path.write_bytes(b'GGUF')
            with patch('serve.local_vision.projector',return_value=path),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=10*1024**3)):
                result=budget(resources,{'vision':True,'vision_device':'gpu','gpu':True})
                self.assertFalse(result['options'][0]['fits'])
                self.assertGreater(result['options'][0]['gpu_required_gib'],1)
