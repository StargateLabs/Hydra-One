import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from serve.harness_updates import latest,HarnessUpdates,selected
class HarnessUpdateTests(unittest.TestCase):
 def test_official_registry_identity(self):
  import io
  with patch('serve.harness_updates.urllib.request.urlopen',return_value=io.BytesIO(json.dumps({'name':'@opencode/cli','version':'2.0.26','repository':{'url':'https://github.com/anomalyco/opencode'}}).encode())):
   self.assertEqual(latest('opencode')['version'],'2.0.26')
  with self.assertRaises(ValueError):latest('unknown')
 def test_activation_preserves_homes_and_rollback(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);candidate=root/'output/updates/harness-candidates/opencode/2.0.26/bin';candidate.mkdir(parents=True);binary=candidate/'opencode.exe';binary.write_bytes(b'validated fixture');home=root/'data/opencode-home';home.mkdir(parents=True);memory=home/'memory.json';memory.write_text('preserve')
   updater=HarnessUpdates(root);updater.job={'state':'validated','kind':'opencode','version':'2.0.26','binary':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'ui_verified':True,'validated_at':1}
   updater.activate('opencode');self.assertEqual(selected(root,'opencode')['version'],'2.0.26');self.assertEqual(memory.read_text(),'preserve')
   binary.write_bytes(b'changed');self.assertIsNone(selected(root,'opencode'));updater.activate('opencode',rollback=True);self.assertIsNone(selected(root,'opencode'));self.assertEqual(memory.read_text(),'preserve')
 def test_cannot_activate_unverified_candidate(self):
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(ValueError):HarnessUpdates(folder).activate('dsh')
if __name__=='__main__':unittest.main()
