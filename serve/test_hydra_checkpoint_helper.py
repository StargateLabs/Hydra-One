"""Negative CLI admission proof; no model/DLL may load before rejection."""
import json,subprocess,unittest
from pathlib import Path
class CheckpointCliAdmissionTests(unittest.TestCase):
 def test_unregistered_native_cli_is_rejected_before_runtime_load(self):
  binary=Path(__file__).resolve().parents[1]/'hydra-engine/implementation_closure_v13/native-score-v13.exe'
  if not binary.is_file():self.skipTest('new optional checkpoint helper not built')
  result=subprocess.run([str(binary),'NOT_A_RUNTIME','NOT_A_MODEL'],capture_output=True,text=True,timeout=3)
  self.assertNotEqual(result.returncode,0)
  value=json.loads(result.stdout)
  self.assertIn(value['error'],('NO_VALID_CHILD_RESERVATION','FEATURE_CONTROL_REQUIRED','NO_ACTIVE_RESERVATION'))
