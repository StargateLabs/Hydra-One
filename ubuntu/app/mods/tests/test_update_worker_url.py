import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch
import tools.verify_audio_update_cpu as worker


class DashboardUrl(unittest.TestCase):
    def test_worker_uses_the_live_dashboard_url(self):
        try:
            with patch.dict(os.environ, {'STRATA_DASHBOARD_URL': 'http://127.0.0.1:8090'}):
                importlib.reload(worker)
                self.assertEqual(worker.BASE, 'http://127.0.0.1:8090')
        finally:
            os.environ.pop('STRATA_DASHBOARD_URL', None)
            importlib.reload(worker)

    def test_gpu_validator_passes_the_dashboard_url(self):
        source = (Path(__file__).resolve().parents[1] / 'serve/update_center.py').read_text(encoding='utf-8')
        self.assertIn('STRATA_DASHBOARD_URL', source)

    def test_update_center_receives_the_dashboard_port(self):
        source = ((Path(__file__).resolve().parents[1] / 'serve/server.py').read_text(encoding='utf-8')
                  + (Path(__file__).resolve().parents[1] / 'mods/hooks.py').read_text(encoding='utf-8'))
        self.assertIn('update_center.port=port', ''.join(source.split()))  # hooks carry it

    def test_hermes_install_applies_the_project_pillow_override(self):
        source = (Path(__file__).resolve().parents[1] / 'serve/harness_updates.py').read_text(encoding='utf-8')
        self.assertIn("'--override'", source)
        self.assertIn('Pillow==13.0.0', source)


if __name__ == '__main__':
    unittest.main()
