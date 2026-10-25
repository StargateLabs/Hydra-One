"""Local protocol fixtures, not real-model or GPU validation."""
import json
import threading
import unittest
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from serve.optional_inference import BackendError, LocalOpenAIBackend


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"data":[{"id":"fixture-model"}]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.body = body
        if body['model'] == 'missing':
            self.send_error(404)
            return
        if body['model']=='slow-headers':time.sleep(.15)
        self.send_response(200)
        if body['stream']:
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.end_headers()
            if body['model'] == 'stalled':
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"start"}}]}\n\n');self.wfile.flush()
                time.sleep(2)
                return
            events = [dict(choices=[dict(delta=dict(content='Ciao è'))]),
                      dict(choices=[dict(delta=dict(tool_calls=[dict(index=0,
                           function=dict(arguments='{"x":1}'))]))]),
                      dict(choices=[], usage=dict(prompt_tokens=3, completion_tokens=4))]
            for event in events:
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            if body['model'] != 'broken':
                self.wfile.write(b'data: [DONE]\n\n')
        else:
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(dict(choices=[dict(message=dict(content='Risposta'))])).encode())


class OptionalInferenceTests(unittest.TestCase):
    def test_model_maximum_is_not_misreported_as_active_context(self):
        metadata=LocalOpenAIBackend.model_metadata(dict(id='native',max_model_len=1048576,owned_by='unsloth'))
        self.assertEqual(metadata['model_max_context'],1048576)
        self.assertIsNone(metadata['active_context'])
        self.assertEqual(metadata['context_source'],'not_reported')
        active=LocalOpenAIBackend.model_metadata(dict(max_model_len=262144,active_context_length=32768))
        self.assertEqual(active['active_context'],32768)
        self.assertIsNone(LocalOpenAIBackend.model_metadata(dict(max_model_len=True))['model_max_context'])
        self.assertEqual(LocalOpenAIBackend.model_metadata(dict(input_modalities=['image','audio','invented']))['input_modalities'],['image','audio'])

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.backend = LocalOpenAIBackend(f'http://127.0.0.1:{cls.server.server_port}/v1')

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_only_explicit_loopback_versioned_endpoints(self):
        for url in ('http://example.com/v1', 'http://127.0.0.1.attacker.test/v1',
                    'http://user:key@127.0.0.1/v1', 'http://127.0.0.1/v1?key=secret',
                    'http://127.0.0.1/other', 'https://127.0.0.1/v1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                LocalOpenAIBackend(url)

    def test_models_and_nonstream_completion(self):
        self.assertEqual(self.backend.models(), [dict(id='fixture-model')])
        result = list(self.backend.chat([dict(role='user', content='Ciao')], 'fixture-model'))
        self.assertEqual(result[0]['choices'][0]['message']['content'], 'Risposta')

    def test_stream_preserves_tools_unicode_usage_and_template_inputs(self):
        messages = [dict(role='developer', content='Italiano'), dict(role='user', content='È corretto?')]
        result = list(self.backend.chat(messages, 'fixture-model', stream=True,
                                       tools=[dict(type='function', function=dict(name='x'))]))
        self.assertEqual(result[0]['choices'][0]['delta']['content'], 'Ciao è')
        self.assertEqual(result[1]['choices'][0]['delta']['tool_calls'][0]['function']['arguments'], '{"x":1}')
        self.assertEqual(result[2]['usage']['completion_tokens'], 4)
        self.assertEqual(self.server.body['messages'], [dict(role='system',content='Italiano'),messages[1]])
        self.assertEqual(self.server.body['model'], 'fixture-model')

    def test_multiple_system_messages_are_combined_before_turns(self):
        messages=[dict(role='system',content='First'),dict(role='user',content='Hello'),dict(role='system',content='Memory')]
        list(self.backend.chat(messages,'fixture-model'))
        self.assertEqual(self.server.body['messages'],[dict(role='system',content='First\n\nMemory'),messages[1]])
        self.assertEqual(len(messages),3)

    def test_missing_model_is_error_without_fallback(self):
        with self.assertRaises(BackendError):
            list(self.backend.chat([dict(role='user', content='Ciao')], 'missing'))

    def test_truncated_stream_is_not_success(self):
        with self.assertRaises(BackendError):
            list(self.backend.chat([dict(role='user', content='Ciao')], 'broken', stream=True))

    def test_cancelled_request_does_not_reach_backend(self):
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(list(self.backend.chat([dict(role='user', content='Ciao')],
                                               'fixture-model', cancel=cancel)), [])

    def test_long_prefill_is_not_limited_by_connection_timeout(self):
        client=LocalOpenAIBackend(f'http://127.0.0.1:{self.server.server_port}/v1',timeout=.05)
        result=list(client.chat([dict(role='user',content='hello')],'slow-headers'))
        self.assertEqual(result[0]['choices'][0]['message']['content'],'Risposta')

    def test_stop_interrupts_a_stalled_stream(self):
        cancel=threading.Event()
        events=self.backend.chat([dict(role='user',content='hello')],'stalled',stream=True,cancel=cancel)
        self.assertEqual(next(events)['choices'][0]['delta']['content'],'start')
        started=time.monotonic();cancel.set()
        self.assertEqual(list(events),[])
        self.assertLess(time.monotonic()-started,1)

    def test_token_budget_and_unknown_options_refused(self):
        with self.assertRaises(ValueError):
            list(self.backend.chat([dict(role='user', content='Ciao')], 'fixture-model', True))
        with self.assertRaises(ValueError):
            list(self.backend.chat([dict(role='user', content='Ciao')], 'fixture-model', shell='anything'))


if __name__ == '__main__':
    unittest.main()
