"""After an applied update the user is offered a restart, and its notice never returns."""
import unittest
from pathlib import Path

from serve.update_restart import (
    restart_pending,
    mark_restart_pending,
    clear_restart_pending,
    restart_command,
    applied_versions,
)

ROOT = Path(__file__).resolve().parents[1]


class UpdateRestartTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir(parents=True, exist_ok=True)

    def test_nothing_pending_before_any_update(self):
        self.assertIsNone(restart_pending(self.root))

    def test_an_applied_update_asks_for_a_restart(self):
        mark_restart_pending(self.root, 'strata', 'v0.1.43.1')
        pending = restart_pending(self.root)
        self.assertEqual(pending['component'], 'strata')
        self.assertEqual(pending['version'], 'v0.1.43.1')

    def test_the_restart_request_names_what_to_restart(self):
        mark_restart_pending(self.root, 'strata', 'v0.1.43.1')
        self.assertIn('strata', restart_pending(self.root)['message'].lower())

    def test_the_restart_is_cleared_once_acknowledged(self):
        mark_restart_pending(self.root, 'strata', 'v0.1.43.1')
        clear_restart_pending(self.root)
        self.assertIsNone(restart_pending(self.root))

    def test_an_applied_version_is_recorded_so_its_notice_never_returns(self):
        mark_restart_pending(self.root, 'strata', 'v0.1.43.1')
        self.assertEqual(applied_versions(self.root), {'strata': 'v0.1.43.1'})

    def test_a_corrupt_marker_never_blocks_the_interface(self):
        (self.root / 'data' / 'update-restart-pending.json').write_text('{ broken', encoding='utf-8')
        self.assertIsNone(restart_pending(self.root))

    def test_the_restart_command_reuses_the_running_arguments(self):
        argv = ['python', '-X', 'utf8', 'serve/server.py', '--engine', 'strata',
                '--config', 'strata.json', '--port', '8090']
        command = restart_command(argv, port=8090)
        self.assertEqual(command['port'], 8090)
        self.assertIn('server.py', command['script'])
        self.assertIn('--engine', command['args'])
        self.assertIn('strata', command['args'])
        self.assertNotIn('serve/server.py', command['args'],
                         'the script belongs in its own field, not in the arguments')

    def test_the_restart_command_keeps_the_mcp_configuration(self):
        argv = ['python', 'serve/server.py', '--engine', 'strata', '--port', '8090',
                '--mcp-config', 'data/mcp-dashboard.json']
        command = restart_command(argv, port=8090)
        self.assertIn('data/mcp-dashboard.json', command['args'])

    def test_a_restart_command_for_another_port_is_refused(self):
        argv = ['python', 'serve/server.py', '--port', '8088']
        with self.assertRaises(ValueError):
            restart_command(argv, port=8090)


if __name__ == '__main__':
    unittest.main()
