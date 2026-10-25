import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
from serve.dependency_supervisor import audit,pinned_requirements,prepare_core_repair,PROFILES
from serve.automatic_updates import build_queue

class DependencySupervisorTests(unittest.TestCase):
    def test_only_pinned_package_names_are_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'requirements.txt'
            path.write_text('numpy==2.5.3; python_version >= "3.12"\njinja2==3.1.6\n')
            self.assertEqual(len(pinned_requirements(path)),2)
            for bad in ('--extra-index-url https://example.org','foo @ https://example.org/foo.whl','../foo','foo>=1'):
                path.write_text(bad)
                with self.assertRaises(ValueError):pinned_requirements(path)

    def test_missing_active_model_is_reported_without_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            cfg=root/'strata-test.json';cfg.write_text(json.dumps({'exe':str(root/'engine.exe'),'args':['--native',str(root/'model.gguf')],'tokenizer':str(root/'tokenizer')}))
            with patch('serve.dependency_supervisor.probe',return_value={'missing':[],'packages':{}}):
                result=audit(root,__import__('sys').executable,cfg)
            row=next(r for r in result['checks'] if r['id']=='model:strata-test.json')
            self.assertEqual(row['state'],'missing');self.assertEqual(len(row['missing']),3)
            self.assertFalse(result['automatic_model_download'])

    def test_broken_environment_is_not_reported_as_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir()
            (root/'data/inference-python-selection.json').write_text(json.dumps({'active':{'python':str(root/'gone/python.exe')}}))
            with patch('serve.dependency_supervisor.probe',return_value={'missing':['jinja2'],'packages':{}}):
                result=audit(root,__import__('sys').executable)
            self.assertEqual(next(r for r in result['checks'] if r['id']=='core')['state'],'missing')
            self.assertEqual(next(r for r in result['checks'] if r['id']=='runtime-python')['state'],'missing')

    def test_recovery_requires_compatible_official_installer(self):
        rows=[{'id':'soup','version':'0.76.0','automatic_update_supported':True},
              {'id':'strata','version':'1','automatic_update_supported':True},
              {'id':'unknown','version':'1','automatic_update_supported':False}]
        default=build_queue({'components':rows})
        self.assertTrue(all(r['state']=='not_installed' for r in default))
        recovered=build_queue({'components':rows},include_missing=True)
        self.assertEqual(recovered[0]['state'],'queued')
        self.assertEqual(recovered[1]['state'],'not_installed')
        self.assertEqual(recovered[2]['state'],'not_installed')

    def test_missing_binary_is_recovered_even_with_a_saved_installed_version(self):
        data={'components':[{'id':'opencode','version':'2.1.0','installed_version':'2.1.0','update_state':'current','automatic_update_supported':True}],
              'dependency_health':{'checks':[{'id':'component:opencode','state':'missing'}]}}
        self.assertEqual(build_queue(data)[0]['state'],'current')
        self.assertEqual(build_queue(data,include_missing=True)[0]['state'],'queued')

    def test_missing_audiocraft_uses_existing_isolated_official_installer(self):
        data={'dependency_health':{'checks':[{'id':'audiocraft','state':'missing'}]}}
        self.assertEqual(build_queue(data),[])
        self.assertEqual(build_queue(data,include_missing=True)[0]['type'],'audiocraft')
        from serve.automatic_updates import AutomaticUpdates
        updater=object.__new__(AutomaticUpdates);updater.service=SimpleNamespace(audiocraft_setup=Mock());updater.center=Mock()
        updater.service.audiocraft_setup.status.return_value={'state':'ready','active_python':'isolated/python','selection_error':None}
        item={'type':'audiocraft','id':'audiocraft'};updater.advance(item,{},{});self.assertEqual(item['state'],'complete')
        updater.center.check_dependency_health.assert_called_once()

    def test_core_repair_has_priority_and_keeps_existing_validation_flow(self):
        data={'dependency_health':{'checks':[{'id':'core','state':'missing'}]}}
        row=build_queue(data,include_missing=True)[0]
        self.assertTrue(row['repair_missing']);self.assertEqual(row['type'],'dependency');self.assertEqual(row['environment'],'Strata')

    def test_vendor_runtime_is_not_replaced_by_generic_pypi(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'requirements.txt').write_text('jinja2==3.1.6\n')
            center=SimpleNamespace(root=root,operational_idle=lambda:True)
            with patch('serve.dependency_supervisor.probe',return_value={'packages':{'torch':'2.11.0+rocm7.14.0'}}):
                with self.assertRaisesRegex(ValueError,'vendor'):prepare_core_repair(center)

    def test_repair_waits_while_engine_is_active(self):
        center=SimpleNamespace(operational_idle=lambda:False)
        with self.assertRaisesRegex(ValueError,'Stop active'):prepare_core_repair(center)

    def test_recovery_policy_persists_without_touching_application_sources(self):
        from serve.automatic_updates import AutomaticUpdates
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'custom_mod.py';source.write_text('original modification')
            center=Mock();center.root=root;center.status.return_value={'dependency_health':{'state':'ready','checked_at':1,'checks':[]}}
            service=SimpleNamespace(update_center=center)
            updater=AutomaticUpdates(service,start_worker=False);updater.recover_missing()
            saved=json.loads((root/'data/automatic-updates.json').read_text())
            self.assertTrue(saved['recover_missing_enabled']);self.assertTrue(saved['enabled'])
            self.assertEqual(source.read_text(),'original modification')

    def test_missing_dependency_in_cpu_environment_enters_existing_resolver(self):
        environment={'name':'Strata','python':'python','packages':[{'name':'jinja2','version':'3.1.6'}],
                     'dependency_health':{'state':'broken'},'update_check':{'state':'checked'}}
        self.assertEqual(build_queue({'environments':[environment]}),[])
        row=build_queue({'environments':[environment]},include_missing=True)[0]
        self.assertEqual(row['state'],'queued');self.assertEqual(row['type'],'dependency')

if __name__=='__main__':unittest.main()
