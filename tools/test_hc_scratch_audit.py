import unittest
from tools.audit_hc_scratch import scratch_accesses
class ScratchAuditTests(unittest.TestCase):
 def test_immediate_width_and_overflow(self):
  r=scratch_accesses('scratch_store_b128 off, v[0:3], off offset:920',956)
  self.assertEqual(r['max_immediate_end'],936);self.assertTrue(r['all_immediate_accesses_within_declared'])
  self.assertFalse(scratch_accesses('scratch_load_b128 v[0:3], off, off offset:950',956)['all_immediate_accesses_within_declared'])
 def test_dynamic_address_is_not_misreported_as_verified(self):
  r=scratch_accesses('scratch_load_b32 v0, v1, off offset:1000',956)
  self.assertEqual(r['dynamic_address_count'],1);self.assertEqual(r['max_immediate_end'],0)
if __name__=='__main__':unittest.main()
