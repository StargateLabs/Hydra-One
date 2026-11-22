import unittest

from serve.gpu_safety import preflight_refusal


class GpuSafetyTests(unittest.TestCase):
    def test_gpu_validation_requires_ram_and_commit_headroom(self):
        self.assertIsNone(preflight_refusal(25, 20))
        self.assertIn('RAM', preflight_refusal(15, 20))
        self.assertIn('commit', preflight_refusal(25, 5))
        self.assertIsNone(preflight_refusal(25, None))
