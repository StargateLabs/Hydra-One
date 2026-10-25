import struct,unittest
from serve import hydra_cpu_scheduling as scheduling
class CpuSchedulingTests(unittest.TestCase):
 def test_cpu_set_parser_uses_efficiency_and_group(self):
  def record(index,efficiency,group=0):
   value=bytearray(32);struct.pack_into('<IIIH',value,0,32,0,100+index,group);value[14]=index;value[18]=efficiency;return value
  rows=scheduling.parse_cpu_sets(record(0,1)+record(16,0)+record(17,0)+record(1,0,1))
  self.assertEqual(scheduling.ecore_indices(rows,[0,16,17]),[16,17])
 def test_homogeneous_cpu_and_malformed_buffer_fail_closed(self):
  self.assertEqual(scheduling.ecore_indices([dict(group=0,index=0,efficiency=0,flags=0)],[0]),[])
  with self.assertRaises(ValueError):scheduling.parse_cpu_sets(b'broken')
