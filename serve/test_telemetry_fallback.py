import builtins,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.telemetry import Telemetry

class TelemetryFallbackTests(unittest.TestCase):
    def probe(self,setup_module=None):
        original=builtins.__import__
        def importing(name,*args,**kwargs):
            if name=='setup':
                if setup_module is None:raise ModuleNotFoundError('Setup unavailable')
                return setup_module
            return original(name,*args,**kwargs)
        gpu=SimpleNamespace(ok=lambda:True,name=lambda:'AMD fixture')
        with patch('serve.telemetry.gpu_reader',return_value=gpu),patch('serve.telemetry.threading.Thread'),patch('builtins.__import__',side_effect=importing):
            return Telemetry(amd=True)
    def test_missing_setup_does_not_break_cpu_and_gpu_name_telemetry(self):
        telemetry=self.probe()
        self.assertEqual(telemetry.static['gpu_archs'],[])
        self.assertEqual(telemetry.static['gpu_name'],'AMD fixture')
        self.assertIn('threads',telemetry.static)
    def test_incomplete_setup_helpers_leave_architecture_unknown(self):
        telemetry=self.probe(SimpleNamespace(ROOT=Path('missing')))
        self.assertEqual(telemetry.static['gpu_archs'],[])

if __name__=='__main__':unittest.main()
