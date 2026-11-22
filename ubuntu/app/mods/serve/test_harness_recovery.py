import hashlib,json,os,tempfile,unittest
from pathlib import Path
from serve.harness_updates import staging_candidate

class HarnessRecoveryTests(unittest.TestCase):
 @unittest.skipUnless(os.name=='nt','Windows long path preservation')
 def test_session_backup_preserves_long_paths_and_original_files(self):
  from serve.harness_updates import HarnessUpdates,_native_path
  with tempfile.TemporaryDirectory(dir=str(_native_path(tempfile.gettempdir()))) as folder:
   root=Path(folder);relative=Path(*(['deep-workspace']*16))/'user-mod.json'
   original=_native_path(root/'data/hermes-home'/relative);original.parent.mkdir(parents=True);original.write_text('preserve user mod')
   saved=HarnessUpdates(root).backup_home('hermes')
   self.assertEqual(_native_path(Path(saved)/relative).read_text(),'preserve user mod')
   self.assertEqual(original.read_text(),'preserve user mod')

 def test_hermes_candidate_environment_does_not_require_prior_activation(self):
  from serve.agent_harness import AgentHarness
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'candidate/source';venv=root/'candidate/venv'
   harness=AgentHarness(root/'probe',kind='hermes',binary='python',mcp_servers={})
   environment=harness.environment(hermes_runtime={'source':source,'venv':venv})
   self.assertEqual(environment['VIRTUAL_ENV'],str(venv))
   self.assertEqual(environment['HERMES_WEB_DIST'],str(source/'hermes_cli/web_dist'))
   self.assertTrue(Path(environment['HERMES_HOME']).is_relative_to(root/'probe'))

 def test_missing_binary_uses_fresh_candidate_and_preserves_old_files(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);old=root/'output/updates/harness-candidates/memory/2.0.0';old.mkdir(parents=True)
   manifest=old/'VALIDATED.json';manifest.write_text(json.dumps({'version':'2.0.0','binary':str(old/'missing.js'),'sha256':'0'*64}))
   before=manifest.read_bytes();candidate=staging_candidate(root,'memory','2.0.0')
   self.assertNotEqual(candidate,old);self.assertEqual(candidate.parent,old.parent)
   self.assertEqual(manifest.read_bytes(),before)
 def test_intact_verified_candidate_is_reused(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);old=root/'output/updates/harness-candidates/memory/2.0.0';old.mkdir(parents=True)
   binary=old/'cli.js';binary.write_bytes(b'fixture')
   (old/'VALIDATED.json').write_text(json.dumps({'version':'2.0.0','binary':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}))
   self.assertEqual(staging_candidate(root,'memory','2.0.0'),old)

if __name__=='__main__':unittest.main()
