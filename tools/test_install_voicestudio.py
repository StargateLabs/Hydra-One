import unittest
from tools.install_voicestudio import expected_checksum


class InstallerTests(unittest.TestCase):
    def test_exact_single_release_checksum(self):
        digest='a'*64
        self.assertEqual(expected_checksum(digest+'  VoiceStudio-Electron-0.5.6-win-x64.exe\n','VoiceStudio-Electron-0.5.6-win-x64.exe'),digest)
        for text in ('','bad  VoiceStudio-Electron-0.5.6-win-x64.exe', (digest+'  VoiceStudio-Electron-0.5.6-win-x64.exe\n')*2):
            with self.assertRaises(ValueError):expected_checksum(text,'VoiceStudio-Electron-0.5.6-win-x64.exe')


if __name__=='__main__':unittest.main()
