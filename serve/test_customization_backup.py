import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from serve.customization_backup import snapshot


class CustomizationBackup(unittest.TestCase):
    def test_managed_audio_python_is_excluded_but_mod_and_audio_settings_survive(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for relative in ('data/audiocraft-python/python/Lib','src','data'):
                (root/relative).mkdir(parents=True,exist_ok=True)
            (root/'data/audiocraft-python/python/Lib/runtime.py').write_text('vendor runtime')
            (root/'src/custom.hip').write_text('custom GPU implementation')
            (root/'data/audiocraft-selection.json').write_text('{"custom":true}')
            result=snapshot(root)
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertNotIn('data/audiocraft-python/python/Lib/runtime.py',archive.namelist())
                self.assertIn('src/custom.hip',archive.namelist())
                self.assertIn('data/audiocraft-selection.json',archive.namelist())

    def test_browser_profile_locks_are_outside_editable_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);profile=root/'data/native-workspace/dashboard-profile/Default';profile.mkdir(parents=True)
            (profile/'Profile.lock').write_text('runtime lock')
            (root/'data/native-workspace/state.json').write_text('{}')
            result=snapshot(root)
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertNotIn('data/native-workspace/dashboard-profile/Default/Profile.lock',archive.namelist())
                self.assertIn('data/native-workspace/state.json',archive.namelist())
    def test_mod_source_and_configuration_are_recoverable_and_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'serve/web').mkdir(parents=True)
            original=b'// custom StargateLab improvement\n'
            (root/'serve/web/app.js').write_bytes(original)
            (root/'strata.json').write_text('{"custom":true}',encoding='utf-8')
            (root/'output').mkdir();(root/'output/unrelated.json').write_text('{}')
            result=snapshot(root)
            self.assertTrue(result['verified'])
            self.assertEqual((root/'serve/web/app.js').read_bytes(),original)
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertEqual(archive.read('serve/web/app.js'),original)
                self.assertIn('strata.json',archive.namelist())
                self.assertNotIn('output/unrelated.json',archive.namelist())
                rows=json.loads(archive.read('MOD-BACKUP-MANIFEST.json'))
                row=next(r for r in rows if r['path']=='serve/web/app.js')
                self.assertEqual(row['sha256'],hashlib.sha256(original).hexdigest())

    def test_each_backup_preserves_the_previous_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'custom.py';source.write_text('first')
            first=snapshot(root);source.write_text('second');second=snapshot(root)
            self.assertNotEqual(first['archive'],second['archive'])
            with zipfile.ZipFile(first['archive']) as archive:self.assertEqual(archive.read('custom.py'),b'first')
            with zipfile.ZipFile(second['archive']) as archive:self.assertEqual(archive.read('custom.py'),b'second')

    def test_downloaded_hermes_dependencies_do_not_block_source_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for relative in ('data/hermes-home/cache','data/hermes-home/installs','tools/runtime'):
                (root/relative).mkdir(parents=True)
                (root/relative/'dependency.py').write_text('vendor',encoding='utf-8')
            (root/'tools/runtime/pyvenv.cfg').write_text('home = python',encoding='utf-8')
            (root/'data/hermes-home/config.yaml').write_text('preserve: true',encoding='utf-8')
            result=snapshot(root)
            with zipfile.ZipFile(result['archive']) as archive:
                self.assertIn('data/hermes-home/config.yaml',archive.namelist())
                self.assertNotIn('data/hermes-home/cache/dependency.py',archive.namelist())
                self.assertNotIn('data/hermes-home/installs/dependency.py',archive.namelist())
                self.assertNotIn('tools/runtime/dependency.py',archive.namelist())
