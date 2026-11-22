"""The CPU thread setting must cover the BLAS used by Windows ROCm PyTorch."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from serve.safetensors_runtime import configure_runtime_threads


class CPUThreadTests(unittest.TestCase):
    def torch(self):
        return SimpleNamespace(set_num_threads=Mock(),get_num_threads=lambda:2,
                               version=SimpleNamespace(hip='7.14'))

    def test_loaded_openblas_obeys_requested_cpu_threads(self):
        torch=self.torch()
        blas=SimpleNamespace(openblas_set_num_threads=Mock(),
                             openblas_get_num_threads=Mock(side_effect=[32,2]))
        with patch('serve.safetensors_runtime._loaded_rocm_blas',return_value=blas):
            policy=configure_runtime_threads(torch,2,'cpu')
        torch.set_num_threads.assert_called_once_with(2)
        blas.openblas_set_num_threads.assert_called_once_with(2)
        self.assertEqual(policy['blas_before'],32)
        self.assertEqual(policy['blas_threads'],2)

    def test_unapplied_blas_limit_rejects_before_model_load(self):
        blas=SimpleNamespace(openblas_set_num_threads=Mock(),
                             openblas_get_num_threads=lambda:32)
        with patch('serve.safetensors_runtime._loaded_rocm_blas',return_value=blas):
            with self.assertRaisesRegex(RuntimeError,'OpenBLAS'):
                configure_runtime_threads(self.torch(),2,'cpu')

    def test_gpu_does_not_reconfigure_cpu_blas(self):
        with patch('serve.safetensors_runtime._loaded_rocm_blas') as loaded:
            policy=configure_runtime_threads(self.torch(),2,'cuda')
        loaded.assert_not_called()
        self.assertIsNone(policy['blas_threads'])

    def test_other_cpu_builds_keep_pytorch_thread_control(self):
        with patch('serve.safetensors_runtime._loaded_rocm_blas',return_value=None):
            policy=configure_runtime_threads(self.torch(),2,'cpu')
        self.assertEqual(policy['torch_threads'],2)
        self.assertIsNone(policy['blas_threads'])


if __name__=='__main__':unittest.main()
