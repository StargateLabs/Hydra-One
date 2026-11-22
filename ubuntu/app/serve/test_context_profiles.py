import unittest

from serve.context_profiles import plan


class Gemma4ContextTests(unittest.TestCase):
    def test_missing_head_count_kv_uses_mqa_estimate(self):
        metadata = {
            "general.architecture": "gemma4",
            "gemma4.block_count": 48,
            "gemma4.attention.head_count": 16,
            "gemma4.attention.key_length": 512,
            "gemma4.attention.value_length": 512,
            "gemma4.context_length": 262144,
            "gemma4.attention.sliding_window": 1024,
        }
        result = plan(metadata, 7 * 2**30, 100 * 2**30, gpu_free=10 * 2**30, gpu_total=11 * 2**30)
        self.assertEqual(result["kv_bytes_per_token"], 98304)
        row = next(option for option in result["options"] if option["context"] == 32768)
        self.assertTrue(row["fits"])
        self.assertFalse(row["full_gpu"])

    def test_per_layer_kv_heads_are_summed(self):
        metadata = {
            "general.architecture": "gemma4",
            "gemma4.block_count": 48,
            "gemma4.attention.head_count": 16,
            "gemma4.attention.head_count_kv": [8, 8, 8, 8, 8, 1] * 8,
            "gemma4.attention.key_length": 512,
            "gemma4.attention.value_length": 512,
            "gemma4.context_length": 262144,
        }
        result = plan(metadata, 7 * 2**30, 100 * 2**30, gpu_free=10 * 2**30, gpu_total=11 * 2**30)
        self.assertEqual(result["kv_bytes_per_token"], 2 * 328 * 1024)
        row = next(option for option in result["options"] if option["context"] == 8192)
        self.assertAlmostEqual(row["kv_gib"], 5.125)
        self.assertTrue(row["fits"])
        self.assertTrue(row["mixed_cpu_gpu"])


if __name__ == "__main__":
    unittest.main()
