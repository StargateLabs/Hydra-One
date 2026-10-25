import unittest
import threading
from collections import defaultdict,deque
from unittest.mock import patch
from types import SimpleNamespace
from serve.telemetry import Telemetry
class MissingDiskTests(unittest.TestCase):
 def test_failed_sample_recovers_on_next_tick_without_stale_values(self):
  telemetry=Telemetry.__new__(Telemetry)
  telemetry.lock=threading.Lock();telemetry.hist=defaultdict(deque);telemetry.last_efficiency=None
  calls=[]
  def sample():
   calls.append(1)
   if len(calls)==1:raise OSError('sensor disconnected')
   return {'cpu':12}
  telemetry.sample=sample
  ticks=[]
  def tick(seconds):
   ticks.append(dict(telemetry.now))
   if len(ticks)==2:raise KeyboardInterrupt
  with patch('serve.telemetry.time.sleep',side_effect=tick):
   with self.assertRaises(KeyboardInterrupt):telemetry._loop()
  self.assertTrue(ticks[0]['sample_error'])
  self.assertNotIn('cpu',ticks[0])
  self.assertEqual(ticks[1]['cpu'],12)
  self.assertEqual(list(telemetry.hist['cpu']),[None,12])
 def test_missing_counter_keeps_telemetry_alive_without_false_zero(self):
  telemetry=Telemetry.__new__(Telemetry);telemetry.ps=SimpleNamespace(disk_io_counters=lambda:None);telemetry._disk_prev=(1,2,3)
  self.assertEqual(telemetry._disk(),(None,None));self.assertIsNone(telemetry._disk_prev)
if __name__=='__main__':unittest.main()
