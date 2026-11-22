import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from serve.native_workspace import NativeWorkspace,validated_base_url


class NativeWorkspaceTests(unittest.TestCase):
    def test_only_original_local_dashboard_urls(self):
        self.assertEqual(validated_base_url('http://127.0.0.1:8090'), 'http://127.0.0.1:8090')
        for url in ('https://example.org','http://127.0.0.1:8090/path','http://user@127.0.0.1:8090','http://localhost:8090'):
            with self.assertRaises(ValueError):validated_base_url(url)

    def test_unknown_app_never_launches_or_writes_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=NativeWorkspace(folder)
            with patch.object(manager,'start') as start:
                with self.assertRaises(ValueError):manager.open('../other.exe')
                start.assert_not_called()

    def test_returning_to_host_reuses_process(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=NativeWorkspace(folder);manager.process=Mock();manager.process.poll.return_value=None
            with patch('serve.native_workspace.subprocess.Popen') as popen:
                manager.start()
                popen.assert_not_called()

    def test_commands_keep_app_identity_and_stop_is_graceful(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=NativeWorkspace(folder)
            with patch.object(manager,'start',return_value={'ready':True}),patch.object(manager,'status',return_value={'ready':True}):
                manager.open('claude');command=json.loads(manager.command_file.read_text())
                self.assertEqual(command['action'],'open');self.assertEqual(command['kind'],'claude')
                manager.stop_app('claude');command=json.loads(manager.command_file.read_text())
                self.assertEqual(command['action'],'close');self.assertFalse(command.get('force',False))

    def test_idle_release_does_not_kill_process_or_files(self):
        with tempfile.TemporaryDirectory() as folder:
            manager=NativeWorkspace(folder)
            with patch.object(manager,'status',return_value={'ready':True}),patch('serve.native_workspace.subprocess.Popen') as popen:
                manager.stop_app('antigravity')
                popen.assert_not_called()


if __name__=='__main__':unittest.main()
