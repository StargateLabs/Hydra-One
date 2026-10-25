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
    def test_verified_package_is_selected_automatically(self):
        data={'components':[{'id':'llama.cpp','installed_version':'1','version':'2','update_state':'available','package_selection':{'asset_id':123}}]}
        row=build_queue(data)[0];self.assertEqual(row['state'],'queued');self.assertEqual(row['asset_id'],123)
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
