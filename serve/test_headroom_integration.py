import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path
from serve.headroom_integration import mcp_config, ensure_proxy, status

class HeadroomIntegrationTests(unittest.TestCase):
    def test_project_scoped_contract_uses_official_cli_and_local_state(self):
        root=Path(__file__).resolve().parents[1];row=mcp_config(root)
        self.assertEqual(row['args'],['mcp','serve','--proxy-url','http://127.0.0.1:18198'])
        self.assertTrue(Path(row['command']).is_relative_to(root))
        self.assertTrue(Path(row['env']['HEADROOM_WORKSPACE_DIR']).is_relative_to(root))
        self.assertEqual(row['env']['HEADROOM_TELEMETRY'],'off')

    def test_disabled_or_invalid_activation_never_routes_traffic(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'data/headroom/enabled.json'
            config.parent.mkdir(parents=True)
            for value in ('{"enabled":false}', '{}', 'invalid', '[]'):
                config.write_text(value)
                with patch('urllib.request.urlopen') as request:
                    self.assertEqual(ensure_proxy(root,'http://127.0.0.1:8090'),'http://127.0.0.1:8090')
                    request.assert_not_called()
                self.assertFalse(status(root)['automatic_traffic_compression'])

    def test_unhealthy_proxy_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'data/headroom/enabled.json'
            config.parent.mkdir(parents=True);config.write_text('{"enabled":true}')
            with patch('urllib.request.urlopen') as request, patch('subprocess.Popen') as launch:
                request.return_value.__enter__.return_value.read.return_value=b'{"service":"headroom-proxy","status":"failed","alive":false}'
                with self.assertRaises(RuntimeError):ensure_proxy(root,'http://127.0.0.1:8090')
                launch.assert_not_called()

    def test_enabled_status_describes_harness_scope_not_all_traffic(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'data/headroom/enabled.json'
            config.parent.mkdir(parents=True);config.write_text('{"enabled":true}')
            self.assertEqual(status(root)['compression_scope'],'local_harness_requests_and_on_demand_mcp_tools')

    def test_only_exact_local_upstream_is_routed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'data/headroom/enabled.json'
            config.parent.mkdir(parents=True);config.write_text('{"enabled":true}')
            for base in ('http://example.com:8090','http://127.0.0.1:8088','https://127.0.0.1:8090','http://user:pass@127.0.0.1:8090','http://127.0.0.1:8090/other'):
                with patch('urllib.request.urlopen') as request:
                    self.assertEqual(ensure_proxy(root,base),base)
                    request.assert_not_called()

if __name__=='__main__':unittest.main()
