import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from serve.hydra_http_pool import SerialConnectionPool
class HttpPoolTests(unittest.TestCase):
 def test_consumed_chunked_json_reuses_but_sse_does_not(self):
  raw=Mock();raw.sock=object();response=SimpleNamespace(length=None,isclosed=lambda:True,will_close=False,_hydra_body_consumed=True)
  raw.getresponse.return_value=response;pool=SerialConnectionPool(factory=Mock(return_value=raw))
  first=pool.connection('127.0.0.1',1234,timeout=1);first.getresponse();first.close()
  second=pool.connection('127.0.0.1',1234,timeout=1)
  self.assertEqual(pool.stats['reused'],1)
  del response._hydra_body_consumed
  second.getresponse();second.close();self.assertEqual(pool.stats['discarded'],1)
 def test_complete_json_can_reuse_same_connection(self):
  raw=Mock();raw.sock=object();raw.getresponse.return_value=SimpleNamespace(length=0,isclosed=lambda:True,will_close=False)
  pool=SerialConnectionPool(factory=Mock(return_value=raw))
  first=pool.connection('127.0.0.1',1234,timeout=1);first.getresponse();first.close()
  second=pool.connection('127.0.0.1',1234,timeout=1);second.getresponse();second.close()
  self.assertEqual(pool.stats['reused'],1);pool.close();raw.close.assert_called_once()
 def test_partial_response_is_closed_and_busy_is_refused(self):
  raw=Mock();raw.getresponse.return_value=SimpleNamespace(length=10,isclosed=lambda:False,will_close=False)
  pool=SerialConnectionPool(factory=Mock(return_value=raw));first=pool.connection('127.0.0.1',1234,timeout=1)
  with self.assertRaisesRegex(RuntimeError,'BUSY'):pool.connection('127.0.0.1',1234,timeout=1)
  first.getresponse();first.close();raw.close.assert_called_once();self.assertEqual(pool.stats['discarded'],1)
