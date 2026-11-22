"""Exercise the actual Windows publisher guard without downloading or running a CLI."""
import ast
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == 'nt', 'Windows Authenticode guard')
class ClaudePublisherGuardTests(unittest.TestCase):
    def test_publisher_guard(self):
        tree = ast.parse(Path(__file__).with_name('harness_updates.py').read_text(encoding='utf-8'))
        commands = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and node.value.startswith('$s=Get-AuthenticodeSignature')]
        self.assertEqual(len(commands), 1)
        prelude = ('function Get-AuthenticodeSignature { param($LiteralPath) '
                   '[pscustomobject]@{Status=$env:STRATA_TEST_SIGNATURE_STATUS;'
                   'SignerCertificate=[pscustomobject]@{Subject=$env:STRATA_TEST_SIGNATURE_SUBJECT}} }; ')
        cases = [
            ('Valid', 'CN="Anthropic, PBC", O="Anthropic, PBC", C=US', True),
            ('Valid', 'CN=Anthropic PBC, O=Anthropic PBC, C=US', True),
            ('NotSigned', 'CN="Anthropic, PBC", O="Anthropic, PBC", C=US', False),
            ('HashMismatch', 'CN="Anthropic, PBC", O="Anthropic, PBC", C=US', False),
            ('Valid', 'CN=Anthropic PBC, O=Other Company, C=US', False),
            ('Valid', 'CN=Other, O="Fake Anthropic, PBC", C=US', False),
            ('Valid', 'CN=Other, O="Anthropic, PBC Evil", C=US', False),
        ]
        with tempfile.TemporaryDirectory() as folder:
            for status, subject, allowed in cases:
                with self.subTest(status=status, subject=subject):
                    report = Path(folder) / 'signature.json'
                    env = dict(os.environ, STRATA_CLAUDE_CANDIDATE='unused.exe',
                               STRATA_CLAUDE_SIGNATURE=str(report),
                               STRATA_TEST_SIGNATURE_STATUS=status, STRATA_TEST_SIGNATURE_SUBJECT=subject)
                    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                                             prelude + commands[0]], env=env, capture_output=True,
                                            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode == 0, allowed, result.stderr.decode(errors='replace'))
                    self.assertEqual(json.loads(report.read_text(encoding='utf-8-sig'))['status'], status)


if __name__ == '__main__':
    unittest.main()
