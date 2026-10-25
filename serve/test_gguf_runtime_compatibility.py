import unittest
import tempfile
import hashlib
import json
from pathlib import Path
from serve.gguf_runtime_compatibility import unsupported_reason

class CompatibilityTests(unittest.TestCase):
    def test_prism_requires_verified_manifest_and_unchanged_binary(self):
        from serve.gguf_runtime_compatibility import prism_binary
        with tempfile.TemporaryDirectory() as folder:
            parent=Path(folder);root=parent/'app';(root/'data').mkdir(parents=True)
            runtime=parent/'HYDRA/prism_integration_20261017/runtime';runtime.mkdir(parents=True)
            binary=runtime/'llama-server.exe';binary.write_bytes(b'fixture')
            self.assertIsNone(prism_binary(root,gpu=True))
            manifest=dict(schema=1,directory=str(runtime),device='ROCm0',real_inference_verified=True,
                          files=[dict(path='llama-server.exe',sha256=hashlib.sha256(binary.read_bytes()).hexdigest())])
            (root/'data/hydra-prism-runtime.json').write_text(json.dumps(manifest),encoding='utf-8')
            self.assertEqual(prism_binary(root,gpu=True),binary.resolve())
            self.assertIsNone(prism_binary(root,gpu=False))
            binary.write_bytes(b'modified')
            self.assertIsNone(prism_binary(root,gpu=True))

    def test_file_roles_are_distinct_from_runtime_support(self):
        from serve.gguf_runtime_compatibility import file_role, requires_prism
        self.assertEqual(file_role('Ternary-Bonsai-2-27B-mmproj-BF16.gguf'),'projector')
        self.assertEqual(file_role('Qwen3.8-Flash-Next-experimental-speed-projection.gguf'),'controlvector')
        self.assertEqual(file_role('Ternary-Bonsai-2-27B-PQ2_0.gguf'),'model')
        self.assertTrue(requires_prism('Ternary-Bonsai-2-27B-F16.gguf'))
        self.assertFalse(requires_prism('Qwen3.5-4B-UD-Q4_K_XL.gguf'))

    def test_auxiliary_and_prism_formats(self):
        for name in ('Ternary-Bonsai-2-27B-PQ2_0.gguf','Bonsai-PTQ1_0.gguf','DeepSeek-V4.1-Flash-DSpark.gguf','Qwen-DFLASH.gguf','Qwen3.8-Flash-Next-experimental-speed-projection.gguf','Qwen3.8-Flash-Next-MTP-BF16.gguf'):
            with self.subTest(name=name):self.assertIsNotNone(unsupported_reason(name))
    def test_complete_mtp_models_remain_available(self):
        for name in ('Qwen3.5-4B-UD-Q4_K_XL.gguf','Qwen3.5-4B-MTP-Q8_0.gguf','Qwen3.5-4B-MTP-BF16.gguf','Spark-X2.5-4B.gguf','Bonsai-F16.gguf'):
            with self.subTest(name=name):self.assertIsNone(unsupported_reason(name))
