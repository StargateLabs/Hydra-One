import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock


class LauncherTests(unittest.TestCase):
    def test_codex_has_private_proxy_and_state(self):
        from tools.headroom_mcp_launcher import launch
        child=Mock();child.wait.return_value=0;spawn=Mock(return_value=child)
        launch(Path.cwd(),ensure=lambda *a:'http://127.0.0.1:18199',spawn=spawn,is_enabled=lambda _:True)
        args=spawn.call_args.args[0];env=spawn.call_args.kwargs['env']
        self.assertEqual(args[-1],'http://127.0.0.1:18199')
        self.assertTrue(env['HEADROOM_WORKSPACE_DIR'].endswith('codex-mcp'))
        self.assertTrue(env['HEADROOM_CONFIG_DIR'].endswith('codex-mcp/config') or env['HEADROOM_CONFIG_DIR'].endswith('codex-mcp\\config'))

    def test_proxy_is_ready_before_mcp_start(self):
        from tools.headroom_mcp_launcher import launch
        order=[];child=Mock();child.wait.return_value=0
        def ensure(*args):order.append('healthy');return 'http://127.0.0.1:18199'
        def spawn(*args,**kwargs):order.append('mcp');return child
        self.assertEqual(launch(Path.cwd(),ensure=ensure,spawn=spawn,is_enabled=lambda _:True),0)
        self.assertEqual(order,['healthy','mcp'])

    def test_running_mcp_recovers_proxy_without_restarting_mcp(self):
        from tools.headroom_mcp_launcher import launch
        ensure=Mock(return_value='http://127.0.0.1:18199');child=Mock()
        child.wait.side_effect=[subprocess.TimeoutExpired('fixture',5),0]
        spawn=Mock(return_value=child)
        self.assertEqual(launch(Path.cwd(),ensure=ensure,spawn=spawn,is_enabled=lambda _:True),0)
        self.assertEqual(ensure.call_count,2);spawn.assert_called_once()

    def test_disabled_marker_does_not_start_proxy(self):
        from tools.headroom_mcp_launcher import launch
        ensure=Mock();child=Mock();child.wait.return_value=0;spawn=Mock(return_value=child)
        launch(Path.cwd(),ensure=ensure,spawn=spawn,is_enabled=lambda _:False)
        ensure.assert_not_called()
        self.assertNotIn('--proxy-url',spawn.call_args.args[0])

    def test_unknown_proxy_is_not_accepted(self):
        from tools.headroom_mcp_launcher import launch
        spawn=Mock()
        with self.assertRaises(RuntimeError):
            launch(Path.cwd(),ensure=lambda *a:'http://other',spawn=spawn,is_enabled=lambda _:True)
        spawn.assert_not_called()
