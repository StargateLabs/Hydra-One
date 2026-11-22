import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from serve import colibri_update

class ColibriUpdateTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.home=self.root/'data/colibri';self.home.mkdir(parents=True)
  self.old=self.home/'runtime/old';self.old.mkdir(parents=True);(self.old/'qwen36.exe').write_bytes(b'old-engine')
  self.config={'engine':str(self.old/'qwen36.exe'),'launcher':str(self.old/'coli'),'engine_source':'release v1.0.0','backend':'vulkan','family':'qwen36','model_dir':str(self.root/'models/colibri/qwen'),'env':{'CTX':'65536','COLI_VULKAN':'1'},'args':['web','--model',str(self.root/'models/colibri/qwen'),'--host','127.0.0.1','--port','18889'],'host':'127.0.0.1','port':18889}
  self.path=self.home/'setup.json';self.path.write_text(json.dumps(self.config),encoding='utf-8')
  self.directory=self.root/'output/updates/candidates/test';self.directory.mkdir(parents=True)
  for name in ('qwen36.exe','coli'):(self.directory/name).write_bytes(b'new-'+name.encode())
  files=[{'path':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in self.directory.iterdir()]
  self.candidate={'candidate_directory':str(self.directory),'files':files,'sha256':'a'*64,'source':'https://github.com/JustVugg/colibri/releases/download/v2.0.0/colibri-v2.0.0-windows-x86_64.zip','published_version':'v2.0.0'}
 def validated(self):
  with patch.object(colibri_update,'_exercise',return_value={'passed':True,'backend':'vulkan','usage':{'completion_tokens':2}}):return colibri_update.validate(self.root,self.candidate)
 def test_unvalidated_or_changed_candidate_never_activated(self):
  with self.assertRaises(ValueError):colibri_update.activate(self.root,self.candidate)
  candidate=self.validated();(self.directory/'qwen36.exe').write_bytes(b'changed')
  with self.assertRaises(ValueError):colibri_update.activate(self.root,candidate)
  self.assertEqual(json.loads(self.path.read_text()),self.config)
 def test_config_changes_invalidate_candidate(self):
  candidate=self.validated();self.path.write_text(json.dumps({**self.config,'port':18890}))
  with self.assertRaises(ValueError):colibri_update.activate(self.root,candidate)
 def test_activate_and_rollback_preserve_configuration(self):
  candidate=self.validated();colibri_update.activate(self.root,candidate)
  active=json.loads(self.path.read_text());self.assertEqual(active['model_dir'],self.config['model_dir']);self.assertEqual(active['args'],self.config['args']);self.assertEqual(active['env']['CTX'],'65536')
  self.assertTrue(Path(active['engine']).is_relative_to(self.directory));colibri_update.rollback(self.root)
  self.assertEqual(json.loads(self.path.read_text()),self.config)
 def test_reserved_gpu_refuses_validation(self):
  (self.root/'data/.gpu-campaign.lock').write_text('{}')
  with self.assertRaises((ValueError,RuntimeError)):colibri_update.validate(self.root,self.candidate)
 def test_rollback_preserves_later_user_context(self):
  colibri_update.activate(self.root,self.validated())
  setup=json.loads(self.path.read_text());setup['env']['CTX']='131072';self.path.write_text(json.dumps(setup))
  colibri_update.rollback(self.root)
  self.assertEqual(json.loads(self.path.read_text())['env']['CTX'],'131072')
 def test_interrupted_commit_is_recoverable(self):
  candidate=self.validated();atomic=colibri_update.atomic_json
  def write(path,data):
   if Path(path).name=='runtime-selection.json' and 'transition' not in data:raise OSError('interrupted registry write')
   return atomic(path,data)
  with patch.object(colibri_update,'atomic_json',side_effect=write):
   with self.assertRaises(OSError):colibri_update.activate(self.root,candidate)
  colibri_update.recover_transition(self.root)
  registry=json.loads((self.home/'runtime-selection.json').read_text())
  self.assertNotIn('transition',registry);self.assertEqual(registry['active']['setup'],json.loads(self.path.read_text()))
  colibri_update.rollback(self.root);self.assertEqual(json.loads(self.path.read_text()),self.config)
 def test_official_windows_vulkan_package_is_queued(self):
  from serve.update_center import recommend_package
  from serve.automatic_updates import build_queue
  row={'id':'colibri','installed_backend':'vulkan','installed_version':'v1.0.0','version':'v2.0.0','update_state':'available','assets':[{'id':2,'name':'colibri-v2.0.0-windows-x86_64.zip','platform_compatibility':{'state':'platform_matches'},'digest':'sha256:'+'a'*64}]}
  row['package_selection']=recommend_package(row)
  self.assertEqual(row['package_selection']['asset_id'],2)
  self.assertEqual(build_queue({'components':[row]})[0]['state'],'queued')
