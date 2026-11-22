import threading
import json
import unittest
from unittest.mock import patch
from serve import test_hydra_client_lifecycle as lifecycle_fixture


class RequestGuardTests(unittest.TestCase):
    def client(self):
        return lifecycle_fixture.ClientLifecycle().client(lambda:True)

    def test_one_extra_guard_thread_per_request(self):
        client=self.client();created=[];original=threading.Thread
        def make(*args,**kwargs):
            worker=original(*args,**kwargs);created.append(worker);return worker
        with patch('serve.hydra_one.threading.Thread',side_effect=make):
            with patch('serve.optional_inference.LocalOpenAIBackend.chat',return_value=iter([{'choices':[]}])):
                self.assertEqual(len(list(client.chat([],model='fixture',stream=True))),1)
        # Timer subclasses Thread and bypasses the patched factory: also inspect
        # registry while the stream is suspended, in the separate test below.
        self.assertEqual(len(created),1)
        self.assertTrue(all(not t.is_alive() for t in created))
        self.assertFalse(client.guards)

    def test_single_registered_guard_and_cancel_drains(self):
        client=self.client();cancel=threading.Event();observed=threading.Event()
        client.Pending=lambda:type('PendingFixture',(),{'cancel':lambda self:observed.set()})()
        def stream(*args,**kwargs):
            yield {'choices':[]}
            self.assertTrue(observed.wait(3))
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',side_effect=stream):
            response=client.chat([],model='fixture',stream=True,cancel=cancel)
            next(response)
            try:
                self.assertEqual(len(next(iter(client.guards.values()))),1)
                cancel.set();self.assertTrue(observed.wait(3))
            finally:response.close()
        self.assertFalse(client.guards)

    def test_deadline_interrupts_blocked_stream_and_guard_terminates(self):
        client=self.client();client.timeout=.01;expired=threading.Event()
        client.Pending=lambda:type('PendingFixture',(),{'cancel':lambda self:expired.set()})()
        def stream(*args,**kwargs):
            self.assertTrue(expired.wait(3));yield {'choices':[]}
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',side_effect=stream):
            with self.assertRaises(TimeoutError):list(client.chat([],model='fixture'))
        self.assertFalse(client.guards)

    def test_utf8_payload_is_compact_without_changing_tool_arguments(self):
        client=self.client();received=[]
        client.local.pending=client.Pending()
        client.adapter.open=lambda *args:(received.append(args) or ('connection','response'))
        body={'messages':[{'role':'user','content':'perché è già pronto?'}],
              'tools':[{'type':'function','function':{'name':'test','parameters':{'type':'object'}}}]}
        client._request('POST','/chat/completions',body)
        wire=received[0][2]
        self.assertEqual(json.loads(wire),body)
        self.assertIn('perché'.encode(),wire)
        self.assertLess(len(wire),len(json.dumps(body).encode()))
        self.assertNotIn(b'": ',wire)

    def test_nonfinite_payload_does_not_reach_adapter(self):
        client=self.client();received=[];client.local.pending=client.Pending()
        client.adapter.open=lambda *args:received.append(args)
        with self.assertRaises(ValueError):client._request('POST','/chat/completions',{'temperature':float('nan')})
        self.assertFalse(received)

    def test_elapsed_telemetry_does_not_depend_on_coarse_monotonic_ticks(self):
        client=self.client()
        with patch('serve.hydra_one.time.monotonic',return_value=10):
            with patch('serve.optional_inference.LocalOpenAIBackend.chat',return_value=iter([{'choices':[]}])):
                list(client.chat([],model='fixture'))
        self.assertGreater(client.diagnostics[-1]['wall_s'],0)
