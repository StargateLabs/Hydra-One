import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from serve import test_hydra_client_lifecycle as fixture


class GuardFailures(unittest.TestCase):
    def client(self):return fixture.ClientLifecycle().client(lambda:True)

    def test_expired_deadline_rejects_late_content(self):
        c=self.client();c.timeout=.01;expired=threading.Event()
        c.Pending=lambda:SimpleNamespace(cancel=expired.set)
        def stream(*args,**kwargs):
            self.assertTrue(expired.wait(3));yield {'choices':[{'delta':{'content':'late'}}]}
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',side_effect=stream):
            with self.assertRaises(TimeoutError):list(c.chat([],model='fixture'))
        self.assertFalse(c.guards)

    def test_guard_failure_is_observable_and_blocks_new_admission(self):
        c=self.client();c.timeout=.01
        def fail():raise OSError('fixture cancel failed')
        c.Pending=lambda:SimpleNamespace(cancel=fail)
        def stream(*args,**kwargs):
            worker=next(iter(c.guards.values()))[0];worker.join(3)
            self.assertFalse(worker.is_alive());yield {'choices':[]}
        with patch('serve.optional_inference.LocalOpenAIBackend.chat',side_effect=stream):
            with self.assertRaisesRegex(RuntimeError,'guard'):list(c.chat([],model='fixture'))
        self.assertTrue(c.closing)
        with self.assertRaisesRegex(RuntimeError,'chius'):next(c.chat([],model='fixture'))
        self.assertTrue(c.diagnostics[-1]['cleanup_errors'])
        self.assertTrue(c.close())

    def test_unknown_guard_liveness_prevents_new_admission(self):
        c=self.client()
        worker=SimpleNamespace(start=lambda:None,ident=None,is_alive=lambda:True)
        with patch('serve.hydra_one.threading.Thread',return_value=worker):
            with patch('serve.optional_inference.LocalOpenAIBackend.chat',return_value=iter([{'choices':[]}])):
                list(c.chat([],model='fixture'))
        self.assertTrue(c.guards);self.assertTrue(c.closing)
        with self.assertRaisesRegex(RuntimeError,'chius'):next(c.chat([],model='fixture'))
