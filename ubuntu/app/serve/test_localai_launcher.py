"""Exercise the launcher's actual port guard without starting user services."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import unittest


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell'), 'Windows PowerShell required')
class LocalAiLauncherTests(unittest.TestCase):
    def check_port(self, port):
        script = Path(__file__).resolve().parents[1] / 'tools/start_localai.ps1'
        command = """$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Launcher syntax error'}
$function=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-LocalAiPortAvailable'},$true)
if(-not $function){throw 'Port guard missing'}
Invoke-Expression $function.Extent.Text
Test-LocalAiPortAvailable -Port ([int]$args[1])
"""
        # Pass paths as environment values, not interpolated shell source.
        command = command.replace('$args[0]', '$env:LOCALAI_TEST_SCRIPT').replace('$args[1]', '$env:LOCALAI_TEST_PORT')
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                                env={**os.environ, 'LOCALAI_TEST_SCRIPT': str(script), 'LOCALAI_TEST_PORT': str(port)},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_free_port_is_available_without_cim(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.assertEqual(self.check_port(port), 'True')

    def test_occupied_port_is_rejected_and_listener_preserved(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.assertEqual(self.check_port(listener.getsockname()[1]), 'False')
            self.assertGreater(listener.fileno(), -1)


if __name__ == '__main__':
    unittest.main()
