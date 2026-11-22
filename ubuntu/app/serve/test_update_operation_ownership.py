import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from serve.automatic_updates import AutomaticUpdates

class OwnershipTests(unittest.TestCase):
 def test_explicit_check_works_without_enabling_automatic_updates(self):
  with tempfile.TemporaryDirectory() as folder:
   center=Mock();center.root=Path(folder);center.status.return_value={'download':{}}
   runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False)
   runner.data['enabled']=False
   runner.check()
   center.check.assert_called_once()
   self.assertFalse(runner.data['enabled'])
 def test_other_harness_version_cannot_complete_requested_update(self):
  runner=object.__new__(AutomaticUpdates);runner.complete=Mock();runner.activate_harness=Mock()
  with self.assertRaisesRegex(ValueError,'ownership|identit|version'):
   runner.advance({'id':'hermes','type':'harness','version':'2'}, {}, {'kind':'hermes','version':'1','state':'selected'})
  runner.complete.assert_not_called();runner.activate_harness.assert_not_called()
 def test_other_archive_version_cannot_activate(self):
  runner=object.__new__(AutomaticUpdates);runner.center=Mock();runner.complete=Mock()
  with self.assertRaisesRegex(ValueError,'ownership|identit|version'):
   runner.advance({'id':'llama.cpp','type':'archive','version':'2'}, {}, {'component':'llama.cpp','version':'1','state':'validated','result':{'runtime_validated':True}})
  runner.center.activate.assert_not_called();runner.complete.assert_not_called()
 def test_replaced_dependency_plan_cannot_install(self):
  runner=object.__new__(AutomaticUpdates);runner.center=Mock();runner.complete=Mock()
  with self.assertRaisesRegex(ValueError,'ownership|identit|plan'):
   runner.advance({'id':'Strata','type':'dependency','environment':'Strata','operation_plan':'original'}, {}, {'name':'Strata','plan_directory':'replacement','state':'resolved'})
  runner.center.install_dependencies.assert_not_called()

class ArchiveIdentityTests(unittest.TestCase):
 def test_same_version_other_asset_cannot_activate(self):
  runner=object.__new__(AutomaticUpdates);runner.center=Mock();runner.complete=Mock()
  snapshot={'components':[{'id':'llama.cpp','assets':[{'id':7,'url':'official-cpu.zip','digest':'sha256:'+'a'*64}]}]}
  job={'component':'llama.cpp','version':'2','state':'validated','result':{'source':'other-gpu.zip','sha256':'a'*64,'runtime_validated':True}}
  with self.assertRaisesRegex(ValueError,'ownership|archive|asset'):
   runner.advance({'id':'llama.cpp','type':'archive','version':'2','asset_id':7},snapshot,job)
  runner.center.activate.assert_not_called();runner.complete.assert_not_called()

class StagingRecoveryTests(unittest.TestCase):
 def test_verified_download_without_manifest_can_be_reused(self):
  import hashlib
  from serve.update_center import UpdateCenter
  with tempfile.TemporaryDirectory() as folder:
   center=UpdateCenter(folder);center.folder.mkdir(parents=True)
   digest=hashlib.sha256(b'abc').hexdigest();name='strata-windows-x64.zip'
   asset={'id':1,'name':name,'bytes':3,'digest':'sha256:'+digest,'url':'https://github.com/Niko1221/Strata/releases/download/v1/'+name}
   center.result['components']=[{'id':'strata','repository':'Niko1221/Strata','version':'v1','assets':[asset]}]
   target=center.folder/(digest[:12]+'-'+name);target.write_bytes(b'abc')
   center.stage('strata',1)
   self.assertEqual(center.job['state'],'staged')
   self.assertTrue(center.job['reused_verified_copy'])
   self.assertTrue(target.with_name(target.name+'.json').is_file())
 def test_selected_strata_version_does_not_require_legacy_build_manifest(self):
  import hashlib,json
  from serve.update_center import UpdateCenter
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'data').mkdir();candidate=root/'candidate';candidate.mkdir()
   exe=candidate/'strata.exe';exe.write_bytes(b'fixture')
   config=root/'selected.json';config.write_text(json.dumps({'exe':str(exe)}))
   (root/'data/strata-runtime-selection.json').write_text(json.dumps({'active':{'config':str(config),'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'version':'v2','directory':str(candidate)}}))
   center=UpdateCenter(root)
   self.assertEqual(center.installed_versions().get('strata',{}).get('installed_version'),'v2')

class OptionalSelectionTests(unittest.TestCase):
 def test_explicitly_unselected_runtime_is_not_reported_missing(self):
  import json,sys
  from unittest.mock import patch
  from serve.dependency_supervisor import audit
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'data').mkdir()
   (root/'data/runtime-selection.json').write_text(json.dumps({'active':None,'previous':{'binary':'previous-only'}}))
   with patch('serve.dependency_supervisor.probe',return_value={'missing':[],'packages':{}}):
    report=audit(root,sys.executable)
   row=next(r for r in report['checks'] if r['id']=='runtime-selection.json')
   self.assertEqual(row['state'],'not_selected')
   self.assertEqual(row['missing'],[])

class HeavyAutomaticValidationTests(unittest.TestCase):
 def test_unverified_native_strata_does_not_load_large_profile_automatically(self):
  runner=object.__new__(AutomaticUpdates);runner.center=Mock();runner.complete=Mock()
  item={'id':'strata','type':'archive','version':'2'}
  runner.advance(item,{'strata_candidate_validation_current':False},{'component':'strata','version':'2','state':'prepared'})
  runner.center.validate_strata_inference.assert_not_called()
  self.assertEqual(item['state'],'protected')
