import threading
import unittest
from serve import test_hydra_native as fixture
from serve.hydra_native import generate,set_enabled,status


class NativeCompletion(unittest.TestCase):
    def test_stop_token_observed_before_consumer_close_is_completion(self):
        svc,_=fixture.NativeContract().service();svc.stop_ids={8};set_enabled(svc,True)
        stream=generate(svc,[1],3,{},threading.Event())
        self.assertEqual(next(stream),7);self.assertIsNone(next(stream));self.assertEqual(next(stream),8)
        stream.close()
        self.assertEqual(status(svc)['last_outcome'],'completed')

    def test_close_without_stop_or_cancellation_is_not_claimed_cancelled(self):
        svc,_=fixture.NativeContract().service();set_enabled(svc,True)
        stream=generate(svc,[1],3,{},threading.Event());next(stream);stream.close()
        self.assertEqual(status(svc)['last_outcome'],'consumer_closed')
