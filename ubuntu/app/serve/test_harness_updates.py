import json,tempfile,unittest,hashlib
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.harness_updates import latest,HarnessUpdates,selected,node_runtime,_mcp_evidence
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
   updater.activate('opencode');self.assertEqual(selected(root,'opencode')['version'],'2.0.26');self.assertEqual(updater.job.get('version'),'2.0.26');self.assertEqual(memory.read_text(),'preserve')
   binary.write_bytes(b'changed');self.assertIsNone(selected(root,'opencode'));updater.activate('opencode',rollback=True);self.assertIsNone(selected(root,'opencode'));self.assertEqual(memory.read_text(),'preserve')
 def test_cannot_activate_unverified_candidate(self):
  with tempfile.TemporaryDirectory() as folder:
   with self.assertRaises(ValueError):HarnessUpdates(folder).activate('dsh')
 def test_browser_validation_uses_the_dashboard_port(self):
  with tempfile.TemporaryDirectory() as folder:
   self.assertEqual(HarnessUpdates(Path(folder),port=8123).health_url,'http://127.0.0.1:8123/health')
 def test_portable_node_runtime_is_preferred(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);node=root/'node.exe';node.write_bytes(b'fixture');npm=root/'npm-cli.js';npm.write_bytes(b'fixture')
   with patch('serve.portable_runtimes.selected',return_value={'binary':str(node),'npm':str(npm)}),patch('serve.portable_runtimes.environment',return_value={'PATH':'portable'}):
    found=node_runtime(root)
   self.assertEqual(found[0],node);self.assertEqual(found[1],npm);self.assertEqual(found[2],{'PATH':'portable'})
 def test_mcp_failure_keeps_actionable_evidence(self):
  probe=SimpleNamespace(stderr=deque(['launch failed','browser closed']))
  text=_mcp_evidence(probe,{'isError':True,'content':[{'text':'boom'}]})
  self.assertIn('browser closed',text);self.assertIn('boom',text);self.assertLessEqual(len(text),900)
 def test_hermes_candidate_includes_and_checks_native_acp(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'data').mkdir();uv=root/'.venv/Scripts/uv.exe';uv.parent.mkdir(parents=True);uv.write_bytes(b'fixture')
   updater=HarnessUpdates(root);seen=[]
   def run(command,**kwargs):
    if '-e' in command:
     self.assertTrue(command[-1].endswith('[web,mcp,acp]'));seen.append('extra')
    if '-c' in command:
     self.assertIn('import acp',command[-1]);seen.append('import');raise RuntimeError('stop before UI')
   updater.run_owned=run;updater.lock.acquire()
   with patch('serve.hermes_integration.runtime',return_value={'python':'fixture-python'}):
    updater._install_hermes('hermes','0.22.2')
   self.assertEqual(seen,['extra','import']);self.assertEqual(updater.job['error'],'stop before UI')
if __name__=='__main__':unittest.main()
