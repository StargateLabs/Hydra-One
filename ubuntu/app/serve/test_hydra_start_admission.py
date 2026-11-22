"""HYDRA denials must occur before acquiring resources or starting a worker."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from serve.optional_backends import OptionalBackends


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backend = OptionalBackends(self.root, discover_models=False)
        self.addCleanup(self.backend.close)
        self.payload = dict(mode='safetensors', engine_addon='hydra-one',
                            model_path=str(self.root), context=1024, gpu=False,
                            fit_mode='manual', runtime={'threads': 2})

    def assert_idle(self):
        self.assertEqual(self.backend.state['status'], 'idle')
        self.assertIsNone(self.backend.lease)
        self.assertIsNone(self.backend.child)

    def test_resolver_denial_precedes_lease_and_worker(self):
        with patch('serve.hydra_control.normalize_start', side_effect=ValueError('resolver denied')), \
             patch('serve.optional_backends.GpuLease') as lease, \
             patch('serve.optional_backends.threading.Thread') as worker:
            with self.assertRaisesRegex(ValueError, 'resolver denied'):
                self.backend.start(self.payload, True)
            lease.assert_not_called()
            worker.assert_not_called()
        self.assert_idle()

    def test_final_resource_denial_precedes_lease_and_worker(self):
        python = self.root / 'python.exe'
        python.touch()
        info = dict(model_max_context=2048, bytes=1024, kv_bytes_per_token=8)
        context = dict(model_max_context=2048, kv_bytes_per_token=8, weights_gib=0.001)
        with patch('serve.hydra_control.normalize_start', return_value=dict(self.payload)), \
             patch('serve.model_engine_requirements.assert_optional_engine'), \
             patch('serve.safetensors_runtime.inspect_model', return_value=info), \
             patch('serve.python_inference_update.selected_python', return_value=python), \
             patch.object(self.backend, 'python_context_plan', return_value=context), \
             patch('psutil.virtual_memory', return_value=SimpleNamespace(available=64 * 2**30)), \
             patch('serve.hydra_control.model_plan', return_value={'available': False, 'reason': 'resource denied'}) as plan, \
             patch('serve.optional_backends.GpuLease') as lease, \
             patch('serve.optional_backends.threading.Thread') as worker:
            with self.assertRaisesRegex(ValueError, 'resource denied'):
                self.backend.start(self.payload, True)
            plan.assert_called_once()
            self.assertEqual(plan.call_args.args[1]['fit_mode'], 'manual')
            lease.assert_not_called()
            worker.assert_not_called()
        self.assert_idle()


if __name__ == '__main__':
    unittest.main()
