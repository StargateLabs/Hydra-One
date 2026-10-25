import unittest
from pathlib import Path
from serve import antigravity_web as web

class OriginalWebTests(unittest.TestCase):
    def test_preview_command_uses_local_services_and_isolated_data(self):
        command=web.command(Path('C:/official/Antigravity.exe'),Path('C:/Strata'),18196,'token')
        self.assertIn('--http_server_port=18196',command)
        self.assertIn('--disable_telemetry',command)
        self.assertIn('--cloud_code_endpoint=http://127.0.0.1:9',command)
        self.assertIn('--exit_on_stdin_close',command)
        self.assertFalse(any('googleapis.com' in item for item in command))
    def test_reserved_or_remote_port_rejected(self):
        for port in (8080,8088,8090,0,'18196',True):
            with self.assertRaises(ValueError):web.command(Path('C:/app/Antigravity.exe'),Path('C:/Strata'),port,'token')

if __name__=='__main__':unittest.main()
