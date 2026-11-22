import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from serve.hydra_recovery import inspect,restore_missing
from serve.automatic_updates import build_queue
from serve.customization_backup import snapshot

class RecoveryTests(unittest.TestCase):
    def fixture(self,folder,name='hydra_lab/graph_hybrid.py'):
        root=Path(folder)/'Strata-main';capsule=root/'HYDRA/recovery';capsule.mkdir(parents=True)
        data=b'original recovered source\n';archive=capsule/'assets.zip'
        with zipfile.ZipFile(archive,'w') as z:z.writestr(name,data)
        row=dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        (capsule/'manifest.json').write_text(json.dumps(dict(schema_version=1,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files=[row])))
        return root,data

    def test_missing_files_are_restored_and_custom_changes_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,data=self.fixture(tmp);target=root.parent/'HYDRA/hydra_lab/graph_hybrid.py'
            self.assertEqual(inspect(root)['missing'],['hydra_lab/graph_hybrid.py'])
            result=restore_missing(root);self.assertEqual(target.read_bytes(),data)
            self.assertFalse(result['existing_files_overwritten'])
            target.write_bytes(b'custom improvement')
            result=restore_missing(root);self.assertEqual(target.read_bytes(),b'custom improvement')
            self.assertEqual(result['changed'],['hydra_lab/graph_hybrid.py'])

    def test_corrupt_capsule_never_writes_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,data=self.fixture(tmp);archive=root/'HYDRA/recovery/assets.zip'
            archive.write_bytes(archive.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'identity'):restore_missing(root)
            self.assertFalse((root.parent/'HYDRA').exists())

    def test_parent_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,data=self.fixture(tmp,'../outside.py')
            with self.assertRaisesRegex(ValueError,'Unsafe'):restore_missing(root)
            self.assertFalse((Path(tmp)/'outside.py').exists())

    def test_recovery_capsule_is_included_in_mod_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,data=self.fixture(tmp)
            result=snapshot(root)
            with zipfile.ZipFile(result['archive']) as z:
                self.assertIn('HYDRA/recovery/assets.zip',z.namelist())

    def test_recovery_requires_enabled_missing_policy_and_local_capsule(self):
        data={'dependency_health':{'checks':[dict(id='hydra-external',state='missing',repair='local_hydra_capsule')]}}
        self.assertEqual(build_queue(data),[])
        self.assertEqual(build_queue(data,include_missing=True)[0]['type'],'hydra-recovery')
        data['dependency_health']['checks'][0]['repair']='recover_original_backup'
        self.assertEqual(build_queue(data,include_missing=True),[])
