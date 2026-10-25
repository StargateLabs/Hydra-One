import copy
import unittest
from serve.hydra_one import requested


class HydraSelection(unittest.TestCase):
    def test_prism_reuses_existing_native_observer_only_when_registered(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from serve.hydra_one import observer_directory
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);native=root/'engine';native.mkdir()
            (native/'amdhip64_7.dll').touch()
            binary=root/'prism/llama-server.exe'
            owner=SimpleNamespace(root=root,binary=binary)
            with patch('serve.gguf_runtime_compatibility.prism_binary',return_value=binary):
                self.assertEqual(observer_directory(owner),native)
            with patch('serve.gguf_runtime_compatibility.prism_binary',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'nessun fallback CPU'):observer_directory(owner)
            binary.parent.mkdir();(binary.parent/'amdhip64_7.dll').touch()
            self.assertEqual(observer_directory(owner),binary.parent)

    def test_legacy_payload_unchanged(self):
        payload=dict(mode='gguf',runtime=dict(threads=2));before=copy.deepcopy(payload)
        self.assertFalse(requested(payload));self.assertEqual(payload,before)
    def test_both_explicit_local_formats(self):
        for mode in ('gguf','safetensors'):
            self.assertTrue(requested(dict(mode=mode,engine_addon='hydra-one')))
    def test_unknown_addon_or_remote_attachment_denied(self):
        for payload in (dict(engine_addon='other'),dict(mode='api',engine_addon='hydra-one')):
            with self.assertRaises(ValueError):requested(payload)
