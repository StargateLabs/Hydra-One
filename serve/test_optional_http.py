"""HTTP routing fixtures: protocol verification, not model performance."""
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from serve.server import make_handler
from serve.optional_backends import OptionalBackends
from serve.optional_inference import LocalOpenAIBackend
from serve.test_optional_inference import Handler as Fixture


class OptionalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.upstream=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        self.worker=threading.Thread(target=self.upstream.serve_forever,daemon=True);self.worker.start()
        self.backend=OptionalBackends(self.tmp.name)
        self.backend.state.update(status='ready',model='fixture-model',api_model='fixture-model',mode='api')
        self.backend.client=LocalOpenAIBackend(f'http://127.0.0.1:{self.upstream.server_port}/v1')
        svc=SimpleNamespace(api_key='fixture-key',cors_origins=[],optional_backends=self.backend,
                            model='native',loaded=lambda:False,engine=SimpleNamespace(max_context=4096,unloaded=True),
                            aliases=[],vision=None,idle_unload_s=900,
                            model_names=lambda:['native','strata'])
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(svc))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def test_disconnected_client_cancels_optional_openai_and_anthropic(self):
        import socket,time
        for endpoint in ('/v1/chat/completions','/v1/messages'):
            started=threading.Event();cancelled=threading.Event()
            def slow_chat(payload,cancel):
                started.set()
                if cancel.wait(3):cancelled.set()
                return
                yield
            original=self.backend.chat;self.backend.chat=slow_chat
            payload=json.dumps({'model':'local/fixture-model','messages':[{'role':'user','content':'hello'}],'max_tokens':32}).encode()
            sock=socket.create_connection(('127.0.0.1',self.server.server_port))
            try:
                sock.sendall((f'POST {endpoint} HTTP/1.0\r\nHost: localhost\r\nAuthorization: Bearer fixture-key\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n').encode()+payload)
                self.assertTrue(started.wait(2),endpoint)
                sock.close()
                self.assertTrue(cancelled.wait(2),endpoint)
                deadline=time.monotonic()+2
                while self.backend.conversation_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
                self.assertFalse(self.backend.conversation_lock.locked())
            finally:sock.close();self.backend.chat=original

    def test_context_preview_returns_json(self):
        self.backend.context_plan=lambda payload:dict(model_max_context=32768,recommended_context=8192,options=[])
        result=self.call('/inference-backends/context-plan',{'model_path':'fixture'})
        # The fixture helper returns the decoded HTTP response.
        self.assertIn('8192',str(result))

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.upstream.shutdown();self.upstream.server_close();self.worker.join();self.backend.stop()

    def call(self,path,body=None,key='fixture-key'):
        request=Request(f'http://127.0.0.1:{self.server.server_port}'+path,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as response:return response.read()

    def test_rescan_routes_to_discovery_without_changing_active_backend(self):
        called=[]
        self.backend.discovery=SimpleNamespace(state={'status':'scanning'},rescan=lambda:called.append(True) or {'status':'scanning'})
        result=json.loads(self.call('/inference-backends/rescan',{}))
        self.assertEqual(result['status'],'scanning');self.assertEqual(called,[True])
        self.assertEqual(self.backend.state['status'],'ready')

    def test_models_include_native_and_explicit_optional_id(self):
        rows=json.loads(self.call('/v1/models'))['data']
        self.assertEqual([row['id'] for row in rows],['native','local/fixture-model','strata'])
        self.assertEqual(rows[-1]['alias_of'],'local/fixture-model')

    def test_stream_preserves_tools_and_public_identity(self):
        tools=[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}]
        result=self.call('/v1/chat/completions',{'model':'local/fixture-model','messages':[{'role':'user','content':'Hello'}],'stream':True,'tools':tools})
        self.assertIn(b'[DONE]',result);self.assertIn(b'tool_calls',result);self.assertIn(b'local/fixture-model',result)
        self.assertEqual(self.upstream.body['model'],'fixture-model');self.assertEqual(self.upstream.body['tools'],tools)

    def test_nonstream_returns_completion_not_delta(self):
        result=json.loads(self.call('/v1/chat/completions',{'model':'local/fixture-model','messages':[{'role':'user','content':'Hello'}]}))
        self.assertEqual(result['choices'][0]['message']['content'],'Risposta')
        self.assertEqual(result['model'],'local/fixture-model')

    def test_completed_response_allows_immediate_regeneration(self):
        payload={'model':'local/fixture-model','messages':[{'role':'user','content':'Hello'}],'stream':True}
        for _ in range(3):
            response=self.call('/v1/chat/completions',payload)
            self.assertIn(b'[DONE]',response)
            self.assertIn(b'local/fixture-model',response)
        result=json.loads(self.call('/v1/chat/completions',{**payload,'stream':False}))
        self.assertEqual(result['choices'][0]['message']['content'],'Risposta')

    def test_missing_model_never_falls_back(self):
        with self.assertRaises(HTTPError) as error:self.call('/v1/chat/completions',{'model':'local/missing','messages':[]})
        self.assertEqual(error.exception.code,404)

    def test_authentication_still_required(self):
        with self.assertRaises(HTTPError) as error:self.call('/inference-backends',key='wrong')
        self.assertEqual(error.exception.code,401)


if __name__=='__main__':unittest.main()
