import unittest
from serve.airllm_updates import release_from_metadata


class ReleaseTests(unittest.TestCase):
    def test_official_package_has_no_binary_download_action(self):
        row = release_from_metadata({'info': {'name': 'airllm', 'version': '3.0.1'}})
        self.assertEqual(row['repository'], 'lyogavin/airllm')
        self.assertEqual(row['assets'], [])
        self.assertFalse(row['runtime_validated'])

    def test_other_package_and_prerelease_are_rejected(self):
        for name, version in [('air-llm', '3.0.1'), ('airllm', '3.1.0rc1')]:
            with self.assertRaises(ValueError):
                release_from_metadata({'info': {'name': name, 'version': version}})
