import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from serve.hydra_one import HydraClient


class ClientLifecycle(unittest.TestCase):
    def test_graph_rejected_by_existing_admission_dispatches_original_once(self):
        import json
        c=self.client(lambda:True);c.local.pending=object();c.closed=False
        messages=[{'role':'user','content':'original'}]
        enriched=messages+[{'role':'user','content':'retrieved data'}]
        c.graph=SimpleNamespace(prepare=lambda *args:enriched,bypass=None)
        c.adapter.engine._request=lambda body:(_ for _ in ()).throw(ValueError('admission'))
        dispatched=[]
        def opened(method,path,body,pending):
            dispatched.append(json.loads(body));return ('connection','response')
        c.adapter.open=opened
        body=dict(messages=messages,model='optional-model',max_tokens=8)
        self.assertEqual(c._request('POST','/chat/completions',body),('connection','response'))
        self.assertEqual(len(dispatched),1)
        self.assertEqual(dispatched[0],body)
        self.assertEqual(c.graph.bypass,'controller_admission')

    def test_nonstream_collects_normalized_sse_and_usage(self):
        c=self.client(lambda:True)
        base=dict(id='fixture',created=1,model='fixture',object='chat.completion.chunk')
        events=[{**base,'choices':[{'index':0,'delta':{'content':'hello'},'finish_reason':None}]},
                {**base,'choices':[{'index':0,'delta':{'content':' world'},'finish_reason':'stop'}]},
                {**base,'choices':[],'usage':{'prompt_tokens':2,'completion_tokens':2,'total_tokens':4}}]
        def upstream(*args,**kwargs):
            self.assertTrue(kwargs['stream'],'HYDRA transport normalizes requests to SSE')
            return iter(events)
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',side_effect=upstream):
            result=list(c.chat([],model='fixture',stream=False))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['object'],'chat.completion')
        self.assertEqual(result[0]['choices'][0]['message']['content'],'hello world')
        self.assertEqual(result[0]['usage']['completion_tokens'],2)
        self.assertFalse(c.guards)

    def test_nonstream_cancel_does_not_publish_partial_completion(self):
        c=self.client(lambda:True);cancel=threading.Event()
        def upstream(*args,**kwargs):
            yield {'choices':[{'delta':{'content':'partial'}}]}
            cancel.set()
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',side_effect=upstream):
            self.assertEqual(list(c.chat([],model='fixture',stream=False,cancel=cancel)),[])
        self.assertFalse(c.guards)

    def client(self, close):
        c=object.__new__(HydraClient)
        c.closed=False;c.closing=False;c.guard_lock=threading.RLock();c.guards={}
        c.adapter=SimpleNamespace(close=close);c.observer=None
        c.Pending=lambda:SimpleNamespace(cancel=lambda:None)
        c.local=threading.local();c.timeout=1;c.diagnostics=[]
        c.adapter.engine=SimpleNamespace(ledger=SimpleNamespace(active=0))
        return c

    def test_close_excludes_new_chat_before_guard_creation(self):
        entered=threading.Event();release=threading.Event();out=[]
        def close():
            entered.set();self.assertTrue(release.wait(3));return True
        c=self.client(close)
        worker=threading.Thread(target=lambda:out.append(c.close()))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            with patch('serve.optional_inference.LocalOpenAIBackend.chat',return_value=iter(())):
                with self.assertRaisesRegex(RuntimeError,'chius'):
                    next(c.chat([],model='fixture'))
            self.assertFalse(c.guards)
            self.assertFalse(c.close())
        finally:
            release.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertEqual(out,[True])
        self.assertTrue(c.closed)

    def test_failed_close_retains_terminal_admission_latch_and_can_drain(self):
        c=self.client(lambda:False)
        self.assertFalse(c.close());self.assertFalse(c.closed)
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',return_value=iter(())):
            with self.assertRaisesRegex(RuntimeError,'chius'):next(c.chat([],model='fixture'))
        c.adapter.close=lambda:True
        self.assertTrue(c.close());self.assertTrue(c.closed)

    def test_active_guards_prevent_close_without_discarding_ownership(self):
        calls=[];c=self.client(lambda:calls.append(1) or True)
        c.guards[1]=('timer','worker')
        self.assertFalse(c.close());self.assertFalse(calls);self.assertIn(1,c.guards)

    def test_observer_close_failure_keeps_client_nonreusable(self):
        c=self.client(lambda:True)
        def fail():raise OSError('observer close')
        c.observer=SimpleNamespace(close=fail)
        with self.assertRaisesRegex(OSError,'observer close'):c.close()
        self.assertFalse(c.closed);self.assertTrue(c.closing)
        self.assertFalse(c.close_in_progress)
        c.observer.close=lambda:None
        self.assertTrue(c.close())

    def test_telemetry_separates_first_packet_and_content_without_invented_backend_times(self):
        c=self.client(lambda:True)
        events=[{'choices':[{'delta':{'role':'assistant'}}]},
                {'choices':[{'delta':{'content':'private text'}}]}]
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',return_value=iter(events)):
            self.assertEqual(list(c.chat([],model='fixture',stream=True)),events)
        row=c.diagnostics[-1]
        self.assertEqual(row['timing_contract'],'strata-hydra-client-v1')
        self.assertLessEqual(row['first_packet_s'],row['first_content_s'])
        self.assertLessEqual(row['first_content_s'],row['wall_s'])
        self.assertIsNone(row['backend_execution_s'])
        self.assertIsNone(row['queue_wait_s'])
        self.assertNotIn('private text',str(row))

