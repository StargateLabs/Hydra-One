import subprocess
import tempfile
import unittest
from pathlib import Path
from serve.local_speech import LocalSpeech
from serve import hydra_execution_v10 as lab


class CandidateLauncher(unittest.TestCase):
    def test_lab_launcher_only_when_a_reservation_exists(self):
        engine = LocalSpeech(Path(tempfile.gettempdir()) / 'strata-speech-launcher-fixture')
        engine.candidate_validation = True
        previous = getattr(lab._local, 'reservation', None)
        try:
            lab._local.reservation = None
            self.assertIs(engine._candidate_launcher(), subprocess.Popen)
            lab._local.reservation = object()
            self.assertIs(engine._candidate_launcher(), lab.guarded_popen)
        finally:
            lab._local.reservation = previous


if __name__ == '__main__':
    unittest.main()
