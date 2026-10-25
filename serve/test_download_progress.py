import unittest
from serve.download_progress import DownloadProgress
class DownloadProgressTests(unittest.TestCase):
 def test_received_and_network_are_distinct_and_rates_are_measured(self):
  clock=[0.0];records=[];tracker=DownloadProgress(1000,records.append,cached=200,clock=lambda:clock[0])
  clock[0]=2;tracker.record('model',300,True);tracker.record('network',150,True)
  self.assertEqual(records[-1]['received_bytes'],500);self.assertEqual(records[-1]['percent'],50)
  self.assertEqual(records[-1]['network_bytes_per_second'],75);self.assertAlmostEqual(records[-1]['eta_seconds'],500/150)
  tracker.finish();self.assertEqual(records[-1]['percent'],100)
 def test_retries_and_clamping_never_invent_more_than_total(self):
  clock=[0.0];records=[];tracker=DownloadProgress(100,records.append,clock=lambda:clock[0])
  clock[0]=2;tracker.record('model',200,True);self.assertEqual(records[-1]['received_bytes'],100)
  clock[0]=4;tracker.record('model',20,True);self.assertEqual(records[-1]['percent'],20);self.assertIsNone(records[-1]['eta_seconds'])
if __name__=='__main__':unittest.main()
