import tempfile
import unittest
from pathlib import Path
from serve.harness_updates import HarnessUpdates


class HomeBackup(unittest.TestCase):
    def test_generated_directories_are_not_backed_up(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home = root / 'data/hermes-home'
            for name in ('cache', 'installs', 'tools'):
                (home / name).mkdir(parents=True)
                (home / name / 'generated.bin').write_bytes(b'x' * 1024)
            (home / 'sessions').mkdir(); (home / 'sessions/s.json').write_text('{}')
            (home / 'config').mkdir(); (home / 'config/c.yaml').write_text('x')
            updater = HarnessUpdates(root)
            destination = Path(updater.backup_home('hermes'))
            self.assertTrue((destination / 'sessions/s.json').is_file())
            self.assertTrue((destination / 'config/c.yaml').is_file())
            self.assertFalse((destination / 'cache').exists())
            self.assertFalse((destination / 'installs').exists())
            self.assertFalse((destination / 'tools').exists())


if __name__ == '__main__':
    unittest.main()
