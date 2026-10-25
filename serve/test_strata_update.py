import hashlib,json,tempfile,time,unittest
from pathlib import Path
from serve.strata_update import activate,rollback

class StrataSelection(unittest.TestCase):
    def test_selection_preserves_mod_settings_and_restores_original_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'output/updates/candidates/test';candidate.mkdir(parents=True)
            exe=candidate/'strata.exe';exe.write_bytes(b'fixture')
            digest=hashlib.sha256(exe.read_bytes()).hexdigest()
            manifest=dict(candidate_directory=str(candidate),files=[dict(path='strata.exe',sha256=digest)])
            config=root/'strata.json';original=dict(exe='old.exe',args=['old'],env={'tuning':'old'},model_name='fixture',tokenizer='fixture-tokenizer',sampling={'temperature':.2},api_key='fixture-secret',display_name='custom mod')
            original_bytes=json.dumps(original,indent=4).encode();config.write_bytes(original_bytes)
            profile={**original,'exe':str(exe),'args':['new'],'env':{},'lib_dirs':[str(candidate)],'backend':'hip'}
            proof=dict(passed=True,full_profile=True,finished_at=time.time(),exe_sha256=digest,validated_configuration=profile,scope='fixture',engine={'version':'0.1.42'},response={'choices':[{'message':{'content':'hello'}}]})
            report=root/'output/verification/strata-v0142-bounded-real.json';report.parent.mkdir(parents=True);report.write_text(json.dumps(proof))
            selected=activate(root,config,manifest)
            current=json.loads(config.read_bytes())
            self.assertEqual(current['exe'],str(exe))
            self.assertEqual(current['args'],original['args'])
            self.assertEqual(current['env'],original['env'])
            for key in ('sampling','api_key','display_name'):self.assertEqual(current[key],original[key])
            rollback(root);self.assertEqual(config.read_bytes(),original_bytes)
            activate(root,config,manifest);config.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Configuration changed'):rollback(root)
            self.assertEqual(config.read_text(),'{}')
            config.write_bytes(original_bytes);exe.write_bytes(b'altered')
            with self.assertRaisesRegex(ValueError,'candidate has changed'):activate(root,config,manifest)

class SharedSelection(unittest.TestCase):
    def test_all_profiles_use_selected_engine_without_changing_model_settings(self):
        from serve.strata_update import selected_configuration
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=root/'output/updates/candidates/test';directory.mkdir(parents=True)
            exe=directory/'strata.exe';exe.write_bytes(b'engine')
            (directory/'BUILD.json').write_text(json.dumps({'version':'0.1.42','lib_dirs':[]}))
            (directory/'CANDIDATE-MANIFEST.json').write_text(json.dumps({'candidate_directory':str(directory),'files':[{'path':'strata.exe','sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}]}))
            previous=root/'output/updates/strata-configs/old.json';previous.parent.mkdir(parents=True);previous.write_text(json.dumps({'exe':str(root/'old.exe')}))
            registry=root/'data/strata-runtime-selection.json';registry.parent.mkdir()
            registry.write_text(json.dumps({'active':{'directory':str(directory),'previous_config':str(previous),'previous_sha256':hashlib.sha256(previous.read_bytes()).hexdigest(),'version':'0.1.42'}}))
            cfg={'exe':str(root/'old.exe'),'args':['--pack','another-model'],'env':{'custom':'1'},'sampling':{'temperature':.2}}
            updated=selected_configuration(root,cfg)
            self.assertEqual(updated['exe'],str(exe));self.assertEqual(updated['args'],cfg['args']);self.assertEqual(updated['env'],cfg['env']);self.assertEqual(updated['sampling'],cfg['sampling'])
            exe.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'candidate changed'):selected_configuration(root,cfg)
            registry.write_text(json.dumps({'active':None}))
            self.assertEqual(selected_configuration(root,cfg),cfg)

if __name__=='__main__':unittest.main()
