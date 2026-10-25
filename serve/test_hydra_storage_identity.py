import unittest
from serve import hydra_one


class StorageIdentity(unittest.TestCase):
    def test_airllm_cpu_is_layer_streaming_without_physical_io_claim(self):
        d=hydra_one.python_storage_identity({'native_loader':'airllm','device':'cpu','architecture':'LlamaForCausalLM'})
        self.assertIn('HYDRA ONE',d['backend'])
        self.assertEqual(d['storage']['strategy'],'backend_layer_streaming')
        self.assertEqual(d['storage']['source'],'observed_models_api')
        self.assertFalse(d['storage']['nvme_device_verified'])
        self.assertIsNone(d['storage']['physical_read_bytes'])
        self.assertFalse(d['storage']['universal_model_support'])

    def test_transformers_is_not_mislabelled_as_layer_streaming(self):
        d=hydra_one.python_storage_identity({'native_loader':'transformers','device':'cpu'})
        self.assertEqual(d['storage']['strategy'],'backend_managed_residency')

    def test_gpu_or_unknown_metadata_is_not_claimed_validated(self):
        for row in [{},{'native_loader':'airllm','device':'cuda'}]:
            self.assertEqual(hydra_one.python_storage_identity(row)['storage']['strategy'],'unknown')
