import tempfile
import unittest
from pathlib import Path
from serve.colibri_workspace import ColibriWorkspace, local_url


class ColibriWorkspaceTests(unittest.TestCase):
    def test_runtime_configuration_preserves_native_settings_and_validates_limits(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'tmp') as folder:
            manager=ColibriWorkspace(folder,lambda:True);manager.home.mkdir(parents=True)
            manager._family_limits=dict(family='qwen36',default=8192,maximum=262144,environment='Q36_MAXT')
            target=manager.home/'setup.json';target.write_text(json.dumps(dict(family='qwen36',env={'COLI_VULKAN':'1'},args=['web','--host','127.0.0.1','--port','18889'])),encoding='utf-8')
            limits=manager.configure_context({'context':65536,'runtime':{'ram':24,'kv_slots':2,'auto_tier':True}})
            saved=json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(limits['configured'],65536);self.assertEqual(saved['env']['Q36_MAXT'],'65536')
            self.assertEqual(saved['env']['COLI_VULKAN'],'1');self.assertIn('--auto-tier',saved['args'])
            self.assertIn('18889',saved['args']);self.assertEqual(limits['runtime']['kv_slots'],'2')
            manager.configure_context({'context':65536,'runtime':{'policy':'quality'}})
            manager.configure_context({'context':65536,'runtime':{'policy':''}})
            self.assertNotIn('--policy',json.loads(target.read_text(encoding='utf-8'))['args'])
            before=target.read_bytes()
            for payload in ({'context':262145},{'context':65536,'runtime':{'kv_slots':0}},{'context':65536,'runtime':{'host':'0.0.0.0'}}):
                with self.assertRaises(ValueError):manager.configure_context(payload)
                self.assertEqual(target.read_bytes(),before)

    def test_only_plain_loopback_endpoints_are_accepted(self):
        self.assertEqual(local_url('http://127.0.0.1:18889/v1'), 'http://127.0.0.1:18889/v1')
        for value in ('https://example.com/v1', 'http://127.0.0.1@evil.test/', 'http://127.0.0.1:8090/', 'file:///tmp/model', 'http://localhost:18889/?token=x'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_url(value)

    def test_missing_source_is_reported_without_start_or_download(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as folder:
            manager = ColibriWorkspace(Path(folder), lambda: True)
            self.assertFalse(manager.status()['installed'])
            with self.assertRaises(ValueError):
                manager.start()
            self.assertFalse((Path(folder) / 'models').exists())

    def test_busy_app_refuses_preparation_before_native_command(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as folder:
            manager = ColibriWorkspace(Path(folder), lambda: False)
            with self.assertRaisesRegex(ValueError, 'attività'):
                manager.prepare({'model': 'qwen36-35b', 'confirmed_bytes': 23100000000})

    def test_api_connection_can_share_only_its_owned_colibri_reservation(self):
        from serve.gpu_lease import GpuLease
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as folder:
            manager = ColibriWorkspace(Path(folder), lambda: True)
            manager.lease = GpuLease(folder, 'colibri-original-workspace').acquire()
            manager.api_endpoint = 'http://127.0.0.1:18889/v1'
            self.assertTrue(manager.api_lease_matches({'url': manager.api_endpoint}))
            self.assertFalse(manager.api_lease_matches({'url': 'http://127.0.0.1:8091/v1'}))
            from serve.optional_backends import OptionalBackends
            from unittest.mock import patch
            connector = OptionalBackends(folder, discover_models=False)
            connector.external_api_lease = manager.api_lease_matches
            with patch('serve.optional_backends.threading.Thread'):
                connector.start({'mode': 'api', 'url': manager.api_endpoint, 'model': 'test'}, True)
            self.assertIsNone(connector.lease)
            self.assertTrue(manager.lease.path.exists())
            manager.lease.release()
            self.assertFalse(manager.api_lease_matches({'url': manager.api_endpoint}))


if __name__ == '__main__':
    unittest.main()
