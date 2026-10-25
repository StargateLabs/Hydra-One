import tempfile,unittest
from pathlib import Path
from serve.component_notifications import newer,preference,available_rows
class Notifications(unittest.TestCase):
 def test_automatic_mode_suppresses_manual_prompts_at_server(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  from serve.generation_routes import get
  handler=Mock();handler._authorized.return_value=True
  updater=Mock();updater.status.return_value={'enabled':True}
  self.assertTrue(get(handler,SimpleNamespace(automatic_updates=updater),'/updates/notifications'))
  self.assertEqual(handler._json.call_args.args[1]['items'],[])
  self.assertEqual(available_rows('.', [{'id':'hermes','installed_version':'0.22.0','version':'0.22.1'}],automatic=True),[])
 def test_version_comparison_never_notifies_unknown_or_same(self):
  self.assertTrue(newer('b11541-mix-2500203','b11542-mix-2500204'))
  self.assertTrue(newer('5.5.0','5.19.0'))
  for old,new in [('1.0','v1.0'),('unknown','v2'),('2.0','1.0'),(None,'1.0')]:self.assertFalse(newer(old,new))
 def test_dismiss_and_snooze_are_component_and_version_specific(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);rows=[{'id':'llama.cpp','installed_version':'b1','version':'b2'},{'id':'transformers','installed_version':'1.0','version':'2.0'}]
   self.assertEqual(len(available_rows(root,rows)),2)
   preference(root,{'component':'llama.cpp','version':'b2','action':'dismiss'});self.assertEqual([row['id'] for row in available_rows(root,rows)],['transformers'])
   rows[0]['version']='b3';self.assertEqual(len(available_rows(root,rows)),2)
   preference(root,{'component':'transformers','version':'2.0','action':'later'});self.assertEqual([row['id'] for row in available_rows(root,rows)],['llama.cpp'])
 def test_unknown_action_refused(self):
  with self.assertRaises(ValueError):preference('.',{'component':'anything','version':'1','action':'dismiss'})

 def test_lightweight_checks_use_official_harness_channels(self):
  from unittest.mock import patch
  from serve.component_notifications import check_releases
  import threading
  class Center:
   lock=threading.Lock()
   result={'components':[{'id':'opencode','version':'v1.19.0'}]}
  center=Center()
  with patch('serve.component_notifications.SOURCES',{'opencode':'anomalyco/opencode'}), patch('serve.harness_updates.latest',return_value={'id':'opencode','version':'2.0.27','assets':[]}) as latest, patch('serve.component_notifications.threading.Thread') as thread:
   thread.side_effect=lambda target,daemon:type('Immediate',(),{'start':lambda self:target()})()
   check_releases(center)
  latest.assert_called_once_with('opencode')
  self.assertEqual(center.result['components'][0]['version'],'2.0.27')
  self.assertFalse(center.notification_check_running)


class ActionabilityTests(unittest.TestCase):
 def test_release_without_managed_installer_is_not_update_now_notification(self):
  with tempfile.TemporaryDirectory() as root:
   rows=[{'id':'soup','installed_version':'0.75.2','version':'0.76.0','automatic_update_supported':False},{'id':'strata','installed_version':'0.1.42','version':'0.1.43.1'}]
   self.assertEqual([row['id'] for row in available_rows(root,rows)],['strata'])
