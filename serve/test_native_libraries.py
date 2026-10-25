import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve.native_libraries import inventory

class NativeLibrariesTests(unittest.TestCase):
    def test_identical_names_are_not_mistaken_for_physical_sharing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'home';engine=root/'engine';engine.mkdir()
            other=home/'.unsloth/audio.cpp';other.mkdir(parents=True)
            (engine/'same.dll').write_bytes(b'first');(other/'same.dll').write_bytes(b'second')
            with patch('pathlib.Path.home',return_value=home),patch('serve.native_libraries.file_version',return_value=None):result=inventory(root)
            self.assertEqual(len(result['shared']),1);self.assertFalse(result['physically_linked'])
            self.assertTrue(all(row['installed_version'] is None for row in result['libraries']))
    def test_hard_linked_files_are_reported_without_loading_or_hashing_dll(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);home=root/'home';engine=root/'engine';engine.mkdir()
            other=home/'.unsloth/audio.cpp';other.mkdir(parents=True)
            source=engine/'shared.dll';source.write_bytes(b'fixture');os.link(source,other/'shared.dll')
            with patch('pathlib.Path.home',return_value=home),patch('serve.native_libraries.file_version',return_value='1.2.3.4'):result=inventory(root)
            self.assertEqual(len(result['physically_linked']),1)
            self.assertEqual(len(result['physically_linked'][0]['copies']),2)
            self.assertFalse(result['loaded_in_process'])

if __name__=='__main__':unittest.main()
