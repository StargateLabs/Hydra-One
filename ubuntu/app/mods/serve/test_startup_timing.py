import tempfile,unittest
from pathlib import Path
from serve.startup_timing import snapshot
class StartupTimingTests(unittest.TestCase):
 def test_logged_phase_times_are_separate_from_total(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'engine.log';path.write_text('strata generate: expert cache 10653 slots, 13.72 GiB of VRAM\nstrata generate: pre-filled 10653 of 10653 slots from the profile in 21.3 s (650 MB/s)\nFileExpertSource: mapped pinned cache complement ready: resident 16.00 GiB, pinned 16.00 GiB in 12 s; page-locked and mapped\n')
   result=snapshot(path);self.assertEqual([p['seconds'] for p in result['phases']],[21.3,12]);self.assertIsNone(result['total_s']);self.assertFalse(result['disk_separately_measured'])
   self.assertEqual(snapshot(path,45)['total_s'],45)
 def test_missing_log_does_not_become_zero(self):self.assertIsNone(snapshot('missing-startup-file'))
if __name__=='__main__':unittest.main()
