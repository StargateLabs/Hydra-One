"""Regression checks for the Ubuntu Phase 1 port, kept out of the deployed archive."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from serve.host_adaptation import thread_proposal
from serve.optional_backends import OptionalBackends, _default_llama_server, _optional_backend_port


class PortAndBinaryTests(unittest.TestCase):
    def test_default_port_keeps_windows_behaviour(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('STRATA_OPTIONAL_PORT', None)
            self.assertEqual(_optional_backend_port(), 8091)

    def test_port_override(self):
        with patch.dict(os.environ, {'STRATA_OPTIONAL_PORT': '8191'}):
            self.assertEqual(_optional_backend_port(), 8191)

    def test_invalid_port_refused(self):
        for value in ('80', 'abc', '70000', '-1'):
            with self.subTest(value=value), patch.dict(os.environ, {'STRATA_OPTIONAL_PORT': value}):
                with self.assertRaises(ValueError):
                    _optional_backend_port()

    def test_binary_override(self):
        with patch.dict(os.environ, {'STRATA_LLAMA_SERVER': '/opt/strata/runtime/llama.cpp/llama-server'}):
            self.assertEqual(_default_llama_server(), Path('/opt/strata/runtime/llama.cpp/llama-server'))

    def test_thread_batch_stays_within_validator(self):
        _, batch, _ = thread_proposal({}, None)
        self.assertLessEqual(batch, 32)

    def test_manager_uses_configured_port(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'STRATA_OPTIONAL_PORT': '8191'}):
            manager = OptionalBackends(Path(folder), discover_models=False)
            self.assertEqual(manager.port, 8191)
            manager.close()


if __name__ == '__main__':
    unittest.main()
