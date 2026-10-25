import threading
import unittest
from types import SimpleNamespace
from serve.hydra_native import set_enabled,generate,status


class NativeContract(unittest.TestCase):
    def service(self):
        calls=[]
        def run(*args,**kwargs):
            calls.append((args,kwargs));yield 7;yield None;yield 8
        svc=SimpleNamespace(engine=SimpleNamespace(generate=run),model='native-fixture',
            fifo=threading.Lock(),status_lock=threading.Lock(),status={'busy':False,'queued':0},
            optional_backends=SimpleNamespace(status=lambda:{'status':'idle'}))
        return svc,calls

    def test_default_off_and_exact_native_delegation(self):
        svc,calls=self.service();self.assertFalse(status(svc)['enabled'])
        cancel=threading.Event();self.assertEqual(list(generate(svc,[1],3,{},cancel)),[7,None,8])
        self.assertEqual(len(calls),1);self.assertFalse(status(svc)['enabled'])

    def test_enabled_preserves_heartbeat_embeddings_and_metrics(self):
        svc,calls=self.service();original=svc.engine;set_enabled(svc,True)
        self.assertIs(svc.engine,original)
        cancel=threading.Event()
        self.assertEqual(list(generate(svc,[1],3,{},cancel,embeddings='fixture')),[7,None,8])
        self.assertEqual(calls[0][1],{'embeddings':'fixture'})
        self.assertEqual(status(svc)['completed'],1)
        self.assertEqual(status(svc)['backend'],'Strata native')
        set_enabled(svc,False);self.assertFalse(status(svc)['enabled'])

    def test_native_harness_binding_uses_same_model(self):
        from serve.harness_model import local_selection
        svc,_=self.service();set_enabled(svc,True)
        svc.engine.max_context=8192
        selection=local_selection(svc)
        self.assertEqual(selection['backend'],'HYDRA ONE · Strata native')
        self.assertEqual(selection['model'],'native-fixture')
        self.assertEqual(selection['context'],8192)

    def test_cancelled_request_is_recorded_without_restart(self):
        svc,calls=self.service();set_enabled(svc,True)
        cancel=threading.Event();stream=generate(svc,[1],3,{},cancel)
        self.assertEqual(next(stream),7);cancel.set();stream.close()
        self.assertEqual(status(svc)['cancelled'],1)
        self.assertEqual(len(calls),1)

    def test_busy_and_optional_backend_prevent_switch(self):
        svc,_=self.service();svc.fifo.acquire()
        with self.assertRaises(RuntimeError):set_enabled(svc,True)
        svc.fifo.release();svc.status['queued']=1
        with self.assertRaises(RuntimeError):set_enabled(svc,True)
        svc.status['queued']=0;svc.optional_backends.status=lambda:{'status':'ready'}
        with self.assertRaises(RuntimeError):set_enabled(svc,True)
        self.assertFalse(status(svc)['enabled'])

    def test_exception_propagates_without_retry(self):
        svc,calls=self.service();set_enabled(svc,True)
        def fail(*a,**k):
            calls.append(1);yield 1;raise OSError('fixture')
        svc.engine.generate=fail
        stream=generate(svc,[1],3,{},threading.Event());self.assertEqual(next(stream),1)
        with self.assertRaises(OSError):next(stream)
        self.assertEqual(len(calls),1);self.assertEqual(status(svc)['failed'],1)
