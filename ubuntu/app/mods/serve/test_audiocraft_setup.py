import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve.audiocraft_setup import AudioCraftSetup

class AudioCraftRecoveryTests(unittest.TestCase):
 def test_missing_candidate_is_reported_without_breaking_update_status(self):
  with tempfile.TemporaryDirectory() as folder:
   manager=AudioCraftSetup(folder)
   with patch('serve.audiocraft_setup.selected_python',side_effect=ValueError('AudioCraft candidate not validated')):
    result=manager.status()
   self.assertEqual(result['active_python'],'')
   self.assertEqual(result['selection_error'],'AudioCraft candidate not validated')
   self.assertFalse(result['busy'])
 def test_project_managed_uv_works_without_old_windows_hermes_installation(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);uv=root/'.venv/Scripts/uv.exe';uv.parent.mkdir(parents=True);uv.write_bytes(b'fixture')
   self.assertEqual(AudioCraftSetup(root)._uv(),uv)

if __name__=='__main__':unittest.main()
