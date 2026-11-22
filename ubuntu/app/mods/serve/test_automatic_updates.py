import tempfile,unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock
from serve.automatic_updates import build_queue,AutomaticUpdates

class AutomaticUpdatesTests(unittest.TestCase):
    def test_native_terminal_activity_blocks_dashboard_restart(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        updater=object.__new__(AutomaticUpdates)
        updater.root=Path(__file__).resolve().parents[1]/'tmp/automatic-updates-idle-fixture'
        terminal=Mock();terminal.status.return_value={'ready':True,'activity_known':False,'busy':False}
        manager=Mock();manager.terminal=terminal;manager.status.return_value={'status':'idle','busy':False}
        updater.service=SimpleNamespace(agent_harness_claude=manager,status={'busy':False})
        self.assertFalse(updater.activities_idle())
        terminal.status.return_value={'ready':True,'activity_known':True,'busy':True}
        self.assertFalse(updater.activities_idle())
        terminal.status.return_value={'ready':True,'activity_known':True,'busy':False}
        self.assertTrue(updater.activities_idle())

    def test_completed_strata_update_restarts_once_when_idle(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder);center.operational_idle.return_value=True;center.status.return_value={}
            service=SimpleNamespace(update_center=center,automatic_restart=Mock())
            runner=AutomaticUpdates(service,start_worker=False);runner.data.update(enabled=True,checked_at=__import__('time').time())
            runner.complete({'id':'strata'});runner.step();runner.step()
            service.automatic_restart.assert_called_once();self.assertFalse(runner.data['restart_required'])
    def test_active_generation_defers_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder);center.operational_idle.return_value=True;center.status.return_value={}
            manager=Mock();manager.status.return_value={'status':'running'}
            service=SimpleNamespace(update_center=center,automatic_restart=Mock(),local_visual=manager)
            runner=AutomaticUpdates(service,start_worker=False);runner.data.update(enabled=True,restart_required=True)
            runner.step();service.automatic_restart.assert_not_called();self.assertEqual(runner.data['state'],'waiting')
    def test_rocm_environment_requires_verified_vendor_plan(self):
        data={'environments':[{'name':'Unsloth','update_check':{'state':'checked'},'packages':[{'name':'torch','version':'2.11+rocm7.14'},{'name':'trl','version':'1','available_version':'2','update_state':'available'}]}]}
        self.assertEqual(build_queue(data)[0]['state'],'protected')
    def test_safe_leaf_environment_queues_vendor_allowlist(self):
        data={'environments':[{'name':'Visuale','packages':[
            {'name':'certifi','version':'1','available_version':'2','update_state':'available'},
            {'name':'datasets','version':'4','available_version':'5','update_state':'available'}]}]}
        rows=[row for row in build_queue(data) if row.get('type')=='vendor_allowlist']
        self.assertEqual(rows[0]['packages'],{'certifi':'2'})
        self.assertEqual(rows[0]['state'],'queued')

    def test_strata_safe_leaf_is_queued_for_the_green_gate(self):
        data={'environments':[{'name':'Strata','packages':[
            {'name':'certifi','version':'1','available_version':'2','update_state':'available'}]}]}
        row=build_queue(data)[0]
        self.assertEqual(row['type'],'vendor_allowlist')
        self.assertEqual(row['packages'],{'certifi':'2'})
        self.assertEqual(row['state'],'queued')

    def test_open_webui_safe_leaf_queues_vendor_allowlist(self):
        data={'environments':[{'name':'Open WebUI','packages':[
            {'name':'certifi','version':'1','available_version':'2','update_state':'available'},
            {'name':'numpy','version':'1','available_version':'2','update_state':'available'}]}]}
        row=build_queue(data)[0]
        self.assertEqual(row['type'],'vendor_allowlist')
        self.assertEqual(row['packages'],{'certifi':'2'})

    def test_broken_vendor_environment_uses_the_repair_resolver(self):
        data={'environments':[{'name':'Strata','dependency_health':{'state':'broken'},'packages':[
            {'name':'jinja2','version':'3.1.6'}]}]}
        row=build_queue(data,include_missing=True)[0]
        self.assertEqual(row['type'],'dependency')
        self.assertEqual(row['state'],'queued')
        self.assertTrue(row['repair_missing'])

    def test_broken_non_strata_vendor_stays_protected(self):
        data={'environments':[{'name':'Visuale','dependency_health':{'state':'broken'},'packages':[
            {'name':'jinja2','version':'3.1.6'}]}]}
        row=build_queue(data,include_missing=True)[0]
        self.assertEqual(row['state'],'protected')
        self.assertFalse(row.get('repair_missing',False))

    def test_environment_without_safe_leaf_stays_protected(self):
        data={'environments':[{'name':'Unsloth','packages':[
            {'name':'torch','version':'2.11+rocm','update_state':'current'},
            {'name':'datasets','version':'4','available_version':'5','update_state':'available'}]}]}
        self.assertTrue(all(row.get('type')!='vendor_allowlist' for row in build_queue(data)))
        self.assertEqual(build_queue(data)[0]['state'],'protected')

    def test_vendor_allowlist_validates_then_activates(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder)
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False)
            item={'id':'environment:Visuale','type':'vendor_allowlist','environment':'Visuale','state':'working','packages':{'certifi':'2'}}
            job={'state':'candidate_installed','name':'Visuale','result':{}}
            runner.advance(item,{'download':job},job)
            center.visual_python.assert_called_with('validate');self.assertTrue(item['validation_started'])
            job={'state':'candidate_installed','name':'Visuale','result':{'visual_validation':{'passed':True}}}
            runner.advance(item,{'download':job},job)
            center.visual_python.assert_called_with('activate');self.assertEqual(item['state'],'complete')

    def test_vendor_allowlist_strata_uses_select_python(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder)
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False)
            item={'id':'environment:Strata','type':'vendor_allowlist','environment':'Strata','state':'working','packages':{}}
            job={'state':'candidate_installed','name':'Strata','result':{'server_suite':{'passed':True},'dashboard_start_verified':True}}
            runner.advance(item,{'download':job},job)
            center.select_python.assert_called_once();self.assertEqual(item['state'],'complete')

    def test_vendor_allowlist_open_webui_uses_document_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder)
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False)
            item={'id':'environment:Open WebUI','type':'vendor_allowlist','environment':'Open WebUI','state':'working','packages':{}}
            job={'state':'candidate_installed','name':'Open WebUI','result':{}}
            runner.advance(item,{'download':job},job)
            center.document_python.assert_called_with('validate');self.assertTrue(item['validation_started'])
            job={'state':'candidate_installed','name':'Open WebUI','result':{'document_validation':{'passed':True}}}
            runner.advance(item,{'download':job},job)
            center.document_python.assert_called_with('activate');self.assertEqual(item['state'],'complete')

    def test_vendor_allowlist_rejects_another_environment_job(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder)
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False)
            item={'id':'environment:Open WebUI','type':'vendor_allowlist','environment':'Open WebUI','state':'working','packages':{}}
            job={'state':'candidate_installed','name':'Visuale','result':{'visual_validation':{'passed':True}}}
            with self.assertRaisesRegex(ValueError,'ownership changed'):runner.advance(item,{'download':job},job)

    def test_dependency_activation_cannot_use_another_environment_job(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder)
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False)
            with self.assertRaises(ValueError):runner.advance({'type':'dependency','environment':'Strata'},{},{'name':'VoiceStudio','state':'candidate_installed'})
            center.select_python.assert_not_called()
    def test_gpu_build_never_uses_generic_latest(self):
        data={'components':[{'id':'pytorch','installed_version':'2.11+rocm','version':'2.14','update_state':'available','version_comparable':False}]}
        queue=build_queue(data);self.assertEqual(queue[0]['state'],'protected');self.assertEqual(queue[0]['id'],'pytorch')
    def test_ambiguous_packages_are_blocked_without_asking_user(self):
        data={'components':[{'id':'llama.cpp','installed_version':'1','version':'2','update_state':'available','package_selection':{'asset_id':None}}]}
        self.assertEqual(build_queue(data)[0]['state'],'protected')
    def test_native_engine_stays_protected_for_operator_validation(self):
        data={'components':[{'id':'strata','installed_version':'0.1.44.1','version':'v0.2.8','update_state':'available','package_selection':{'asset_id':1}}]}
        row=build_queue(data)[0];self.assertEqual(row['state'],'protected');self.assertEqual(row['reason'],'engine_requires_operator_validation')
    def test_verified_package_is_selected_automatically(self):
        data={'components':[{'id':'llama.cpp','installed_version':'1','version':'2','update_state':'available','package_selection':{'asset_id':123}}]}
        row=build_queue(data)[0];self.assertEqual(row['state'],'queued');self.assertEqual(row['asset_id'],123)
    def test_missing_supported_apps_are_queued_without_optional_capability_flag(self):
        data={'components':[{'id':name,'installed_version':None,'version':'4.0.0'} for name in ('airllm','dsh')]}
        self.assertTrue(all(row['state']=='queued' for row in build_queue(data,include_missing=True)))
        self.assertTrue(all(row['state']=='not_installed' for row in build_queue(data)))
    def test_missing_explicitly_blocked_or_unknown_app_is_not_installed(self):
        data={'components':[{'id':'voicestudio','installed_version':None,'version':'1','automatic_update_supported':False},
                            {'id':'unknown','installed_version':None,'version':'1'}]}
        self.assertTrue(all(row['state']=='not_installed' for row in build_queue(data,include_missing=True)))
    def test_queue_rows_carry_policy_metadata(self):
        data={'components':[
            {'id':'pytorch','installed_version':'2.11+rocm','version':'2.15','update_state':'available','version_comparable':False},
            {'id':'hermes','installed_version':'0.22.5','version':'0.23.0','update_state':'available'}]}
        rows={row['id']:row for row in build_queue(data)}
        self.assertFalse(rows['pytorch']['policy']['automatic'])
        self.assertEqual(rows['pytorch']['policy']['reason'],'build_channel_not_verified')
        self.assertTrue(rows['hermes']['policy']['automatic'])
        self.assertEqual(rows['hermes']['policy']['preserve'],['mods','HYDRA','data'])

    def test_current_components_do_not_install(self):
        self.assertEqual(build_queue({'components':[{'id':'claude','update_state':'current','installed_version':'1','version':'1'}]})[0]['state'],'current')
    def test_activities_delay_entire_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder);center.operational_idle.return_value=False
            center.status.return_value={'state':'complete','components':[],'download':{},'harness_update':{}}
            service=SimpleNamespace(update_center=center)
            runner=AutomaticUpdates(service,start_worker=False);runner.data.update(enabled=True,items=[{'id':'llama.cpp','version':'2','asset_id':1,'state':'queued','type':'archive'}])
            runner.step();center.stage.assert_not_called();self.assertEqual(runner.data['state'],'waiting')
    def test_finished_release_check_is_consumed_once(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder);center.status.return_value={'state':'complete','checked_at':42,'components':[]}
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False);runner.data.update(enabled=True,waiting_check=True,checked_at=0)
            runner.step();runner.step();center.check.assert_not_called();self.assertFalse(runner.data['waiting_check'])

    def test_failed_candidate_is_not_activated(self):
        with tempfile.TemporaryDirectory() as folder:
            center=Mock();center.root=Path(folder);center.operational_idle.return_value=True
            center.status.return_value={'state':'complete','download':{'component':'llama.cpp','state':'failed','error':'bad hash'},'harness_update':{}}
            runner=AutomaticUpdates(SimpleNamespace(update_center=center),start_worker=False);runner.data.update(enabled=True,items=[{'id':'llama.cpp','version':'2','state':'working','type':'archive'}])
            runner.step();center.activate.assert_not_called();self.assertEqual(runner.data['items'][0]['state'],'protected')
if __name__=='__main__':unittest.main()
