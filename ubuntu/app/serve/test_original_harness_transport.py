import tempfile
import unittest
from pathlib import Path
from serve.original_harness_transport import Transport,ClaudeTerminal
from serve.antigravity_original import validate_event


class OriginalTransportTests(unittest.TestCase):
    def test_missing_native_debugger_record_is_a_clean_cold_start(self):
        import uuid
        from serve.antigravity_original import AntigravityOriginal
        app=AntigravityOriginal('.')
        app.profile=Path('output/verification')/('absent-native-profile-'+uuid.uuid4().hex)
        self.assertIsNone(app._target())

    def test_antigravity_reconnect_replaces_only_failed_bridge(self):
        from unittest.mock import Mock
        from serve.antigravity_original import AntigravityOriginal
        app=AntigravityOriginal('.')
        native=app.child=Mock();native.poll.return_value=None
        app.transport=Mock();app.transport.child=Mock()
        app.transport.snapshot.side_effect=[{'ready':False},{'ready':True}]
        app._target=Mock(return_value={'webSocketDebuggerUrl':'ws://127.0.0.1:9999/native'})
        app._hide_owned_window=Mock()
        self.assertTrue(app.start()['ready'])
        app.transport.close.assert_called_once()
        app.transport.start.assert_called_once_with({'mode':'antigravity','url':'ws://127.0.0.1:9999/native'})
        native.terminate.assert_not_called();native.kill.assert_not_called()

    def test_closed_native_app_is_not_reported_reconnectable(self):
        from unittest.mock import Mock
        from serve.antigravity_original import AntigravityOriginal
        app=AntigravityOriginal('.');app.transport.snapshot=Mock(return_value={'ready':False});app._target=Mock(return_value=None)
        self.assertFalse(app.status()['reconnectable'])

    def test_old_reader_cannot_change_restarted_transport(self):
        import io,json
        from types import SimpleNamespace
        transport=Transport('.')
        transport.child=SimpleNamespace()
        old=SimpleNamespace(stdout=io.StringIO(json.dumps({'event':'output','data':'old session'})+'\n'))
        transport._read(old)
        self.assertEqual(list(transport.output),[])
        self.assertFalse(transport.ready.is_set())

    def test_bounded_cursor_and_replay(self):
        with tempfile.TemporaryDirectory() as root:
            transport=Transport(root)
            for cursor in range(1,401):transport.output.append((cursor,str(cursor)))
            transport.cursor=400
            self.assertEqual(transport.snapshot(398)['chunks'],['399','400'])
            self.assertTrue(transport.snapshot(1)['reset'])
            self.assertEqual(len(transport.snapshot()['chunks']),300)
            for cursor in (-1,True,'0'):
                with self.assertRaises(ValueError):transport.snapshot(cursor)

    def test_native_input_is_not_an_arbitrary_cdp_proxy(self):
        event=validate_event({'action':'mouse','params':{'type':'mousePressed','x':30,'y':45,'button':'left','clickCount':1,'execute':'forbidden'}})
        self.assertNotIn('execute',event['params'])
        for request in ({'action':'Runtime.evaluate','params':{}},{'action':'resize','width':True,'height':800},{'action':'mouse','params':{'type':'mousePressed','x':-1,'y':2}},{'action':'text','text':'x'*8193}):
            with self.assertRaises(ValueError):validate_event(request)

    def test_unknown_interactive_activity_cannot_be_auto_killed(self):
        class Harness:root=Path('.');home=Path('output/verification/missing-terminal-fixture')
        terminal=ClaudeTerminal(Harness())
        terminal.transport.snapshot=lambda:{'ready':True}
        with self.assertRaises(RuntimeError):terminal.close(automatic=True)

    def test_native_hooks_report_busy_and_preserve_unknown_owner(self):
        import json
        from tools.claude_terminal_activity import update
        with tempfile.TemporaryDirectory() as root:
            marker=Path(root)/'activity.json';marker.write_text(json.dumps({'token':'owned'}))
            update(marker,'foreign',{'hook_event_name':'SessionStart'})
            self.assertEqual(json.loads(marker.read_text()),{'token':'owned'})
            update(marker,'owned',{'hook_event_name':'UserPromptSubmit','prompt':'never record this'})
            self.assertTrue(json.loads(marker.read_text())['busy'])
            self.assertNotIn('never record this',marker.read_text())
            update(marker,'owned',{'hook_event_name':'Stop','stop_hook_active':True})
            self.assertTrue(json.loads(marker.read_text())['busy'])
            update(marker,'owned',{'hook_event_name':'Notification','notification_type':'idle_prompt'})
            self.assertFalse(json.loads(marker.read_text())['busy'])


if __name__=='__main__':unittest.main()
