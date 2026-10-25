import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from serve import antigravity_desktop as desktop


class AntigravityDesktopTests(unittest.TestCase):
    def test_detects_existing_app_without_claiming_local_inference(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as folder:
            binary = Path(folder) / 'Antigravity.exe'
            binary.touch()
            with patch.object(desktop, '_candidates', return_value=[binary]):
                state = desktop.status()
        self.assertTrue(state['installed'])
        self.assertFalse(state['configured'])
        self.assertFalse(state['inference_verified'])
        self.assertFalse(state['desktop_local_endpoint_documented'])

    def test_missing_app_does_not_launch(self):
        with patch.object(desktop, '_candidates', return_value=[]), patch.object(desktop.subprocess, 'Popen') as popen:
            with self.assertRaises(RuntimeError):
                desktop.launch()
            popen.assert_not_called()

    def test_launches_gui_directly_without_shell_or_provider_overrides(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as folder:
            binary = Path(folder) / 'Antigravity.exe'
            binary.touch()
            with patch.object(desktop, '_candidates', return_value=[binary]), patch.object(desktop.subprocess, 'Popen') as popen:
                result = desktop.launch()
                popen.assert_called_once_with([str(binary)], cwd=str(binary.parent), close_fds=True)
        self.assertTrue(result['launched'])
        self.assertFalse(result['desktop']['inference_verified'])


if __name__ == '__main__':
    unittest.main()
