import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from serve.claude_harness import ClaudeHarness
from serve.claude_optional import to_openai, from_openai, stream_events
from serve.harness_updates import latest, HarnessUpdates, selected


class ClaudeTests(unittest.TestCase):
    def test_owned_run_events_sessions_and_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = ClaudeHarness(folder, binary=sys.executable, api_key='test-key')
            harness.start()
            session = harness.session_id
            code = "import json;print(json.dumps({'type':'assistant','session_id':%r,'message':{'content':[{'type':'text','text':'fixture answer'}]}}));print(json.dumps({'type':'result','is_error':False}))" % session
            with patch.object(harness, 'command', return_value=[sys.executable, '-c', code]):
                harness.run({'prompt': 'fixture'})
                deadline = time.monotonic()+5
                while harness.busy and time.monotonic()<deadline: time.sleep(.02)
            state = harness.status()
            self.assertEqual(state['job']['state'], 'completed', state)
            self.assertEqual(state['messages'][-1]['content'], 'fixture answer')
            self.assertTrue(harness.resume)
            self.assertIn('--resume', harness.command('follow-up'))
            restored = ClaudeHarness(folder, binary=sys.executable)
            self.assertEqual(restored.session_id, session)
            env = harness.environment()
            self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'test-key')
            self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8090')
            self.assertTrue(Path(env['CLAUDE_CONFIG_DIR']).is_relative_to(folder))
            self.assertNotIn('--bare', harness.command('follow-up'))
            self.assertNotIn('--dangerously-skip-permissions', harness.command('follow-up'))
            harness.new_session()
            self.assertNotEqual(harness.session_id, session)

    def test_busyguards_and_cwd(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = ClaudeHarness(folder, binary=sys.executable)
            harness.start()
            with self.assertRaises(ValueError): harness.run({'prompt': 'hello', 'cwd': str(Path(folder).parent)})
            harness.busy = True
            for action in (harness.stop, harness.close, harness.new_session, lambda: harness.run({'prompt': 'hello'})):
                with self.assertRaises(ValueError): action()
            self.assertFalse(harness.closing)
            self.assertEqual(harness.environment()['DISABLE_UPDATES'], '1')

    def test_result_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = ClaudeHarness(folder, binary=sys.executable)
            harness.start()
            with patch.object(harness, 'command', return_value=[sys.executable, '-c', "print('{\"type\":\"result\",\"is_error\":true,\"result\":\"fixture error\"}')"]):
                harness.run({'prompt': 'fixture'})
                deadline=time.monotonic()+5
                while harness.busy and time.monotonic()<deadline: time.sleep(.02)
            self.assertEqual(harness.status()['job']['state'], 'error')
            self.assertIn('fixture error', harness.error)

    def test_adapter_tool_ids_usage_and_stream(self):
        payload = to_openai({'model':'local/test','messages':[
            {'role':'assistant','content':[{'type':'tool_use','id':'call_abc','name':'read','input':{'p':'a'}}]},
            {'role':'user','content':[{'type':'tool_result','tool_use_id':'call_abc','content':'ok'}]}]})
        self.assertEqual(payload['messages'][0]['tool_calls'][0]['id'], 'call_abc')
        self.assertEqual(payload['messages'][1]['tool_call_id'], 'call_abc')
        response={'choices':[{'finish_reason':'tool_calls','message':{'tool_calls':payload['messages'][0]['tool_calls']}}], 'usage':{'prompt_tokens':17,'completion_tokens':5}}
        message=from_openai(response,'local/test')
        self.assertEqual(message['content'][0]['id'],'call_abc')
        self.assertEqual(message['usage'],{'input_tokens':17,'output_tokens':5})
        events=list(stream_events(message))
        self.assertEqual(events[-1][0],'message_stop')
        self.assertEqual(events[-2][1]['usage']['output_tokens'],5)
        response.pop('usage')
        with self.assertRaises(ValueError):from_openai(response,'local/test')

    def test_official_latest_and_claude_rollback_preserve_other_selection(self):
        with patch('serve.harness_updates.urllib.request.urlopen', return_value=io.BytesIO(b'2.1.296')):
            self.assertEqual(latest('claude')['update_method'],'isolated_native_claude')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);candidate=root/'output/updates/harness-candidates/claude/2.1.296';candidate.mkdir(parents=True)
            binary=candidate/'claude.exe';binary.write_bytes(b'fixture')
            home=root/'data/claude-home';home.mkdir(parents=True);(home/'session.json').write_text('preserve')
            (root/'data/harness-runtime-selection.json').write_text(json.dumps({'active':{'hermes':{'version':'keep'}},'previous':{}}))
            import hashlib
            updater=HarnessUpdates(root);updater.job={'state':'validated','kind':'claude','version':'2.1.296','binary':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'ui_verified':False,'cli_verified':True,'validated_at':1}
            updater.activate('claude');self.assertTrue(selected(root,'claude')['cli_verified'])
            updater.activate('claude',rollback=True)
            self.assertIsNone(selected(root,'claude'))
            self.assertEqual(json.loads((root/'data/harness-runtime-selection.json').read_text())['active']['hermes']['version'],'keep')
            self.assertEqual((home/'session.json').read_text(),'preserve')


if __name__ == '__main__': unittest.main()

class OptionalThinkingTests(unittest.TestCase):
    def test_explicit_disabled_thinking_is_forwarded_to_local_template(self):
        request={'model':'strata','messages':[{'role':'user','content':'Hello'}],'thinking':{'type':'disabled'}}
        self.assertEqual(to_openai(request)['chat_template_kwargs'],{'enable_thinking':False})
        self.assertNotIn('chat_template_kwargs',to_openai({'model':'strata','messages':[]}))

class BoundedClaudeTests(unittest.TestCase):
    def test_silent_owned_process_is_stopped_at_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            harness=ClaudeHarness(folder,binary=sys.executable);harness.run_timeout_seconds=.15;harness.start()
            with patch.object(harness,'command',return_value=[sys.executable,'-c','import time;time.sleep(30)']):
                harness.run({'prompt':'fixture'})
                deadline=time.monotonic()+5
                while harness.busy and time.monotonic()<deadline:time.sleep(.02)
            self.assertFalse(harness.busy)
            self.assertEqual(harness.status()['job']['state'],'error')
            self.assertIn('tempo massimo',harness.error)
            self.assertIsNone(harness.child)
