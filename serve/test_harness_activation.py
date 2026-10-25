import threading,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from serve.harness_activation import activate_managed
class HarnessActivationTests(unittest.TestCase):
 def test_idle_native_component_is_restarted_after_selection(self):
  manager=Mock();manager.status.return_value={'status':'ready','owned_process':True,'activity_known':True,'busy':False}
  replacement=Mock();replacement.status.return_value={'status':'ready'}
  job=SimpleNamespace(activate=Mock(),lock=threading.Lock(),job={},persist=Mock())
  service=SimpleNamespace(status_lock=threading.Lock(),update_center=SimpleNamespace(harness_updates=job),agent_harness=manager)
  factory=Mock(side_effect=[manager,replacement])
  self.assertEqual(activate_managed(service,'opencode',factory)['status'],'ready')
  manager.stop.assert_called_once();replacement.start.assert_called_once();self.assertTrue(job.job['restart_verified'])
 def test_busy_component_is_never_stopped(self):
  manager=Mock();manager.status.return_value={'status':'ready','busy':True}
  service=SimpleNamespace(update_center=SimpleNamespace(harness_updates=Mock()))
  with self.assertRaises(ValueError):activate_managed(service,'opencode',lambda:manager)
  manager.stop.assert_not_called();service.update_center.harness_updates.activate.assert_not_called()
 def test_failed_new_start_restores_previous_selection(self):
  manager=Mock();manager.status.return_value={'status':'ready','owned_process':True,'activity_known':True,'busy':False}
  replacement=Mock();replacement.start.side_effect=RuntimeError('failed startup')
  job=SimpleNamespace(activate=Mock(),lock=threading.Lock(),job={},persist=Mock())
  service=SimpleNamespace(status_lock=threading.Lock(),update_center=SimpleNamespace(harness_updates=job),agent_harness=manager)
  with self.assertRaisesRegex(RuntimeError,'precedente ripristinata'):activate_managed(service,'opencode',Mock(side_effect=[manager,replacement]))
  self.assertTrue(job.activate.call_args.kwargs['rollback']);manager.start.assert_called_once()
