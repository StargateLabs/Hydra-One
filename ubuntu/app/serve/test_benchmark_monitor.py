import json
from pathlib import Path
import tempfile
import unittest
from serve.benchmark_monitor import snapshot, competing_benchmark
from serve.windows_gpu_identity import adapter_values

class MonitorTests(unittest.TestCase):
    def test_reservation_owner_expiry_and_invalid_port(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output') as directory:
            path=Path(directory)/'snapshot.json'
            data={'updated_at':99,'active':True,'source_port':8089,'label':'probe','metrics':{}}
            path.write_text(json.dumps(data))
            self.assertEqual(competing_benchmark(8088,path,100),'probe')
            self.assertIsNone(competing_benchmark(8089,path,100))
            self.assertIsNone(competing_benchmark(8088,path,110))
            data['source_port']=True
            path.write_text(json.dumps(data))
            self.assertIsNone(competing_benchmark(8088,path,100))
            data.update(source_port=8089,active=False)
            path.write_text(json.dumps(data))
            self.assertIsNone(competing_benchmark(8088,path,100))

    def test_reservation_prevents_engine_restart(self):
        from unittest.mock import patch
        from serve.server import Service,GpuBusy
        service=Service.__new__(Service)
        service.port=8088
        service.loaded=lambda:False
        with patch('serve.benchmark_monitor.competing_benchmark',return_value='probe'):
            with self.assertRaises(GpuBusy):service.ensure_loaded()

    def test_live_stale_and_missing_snapshot(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'output') as directory:
            path=Path(directory)/'snapshot.json'
            self.assertIsNone(snapshot(path,100))
            path.write_text(json.dumps({'updated_at':99,'active':True,'metrics':{'live':{'state':'reading'}}}))
            self.assertTrue(snapshot(path,100)['active'])
            self.assertFalse(snapshot(path,110)['active'])
            self.assertTrue(snapshot(path,110)['stale'])
            path.write_text('invalid')
            self.assertIsNone(snapshot(path,100))
    def test_amd_counter_does_not_use_first_intel_adapter(self):
        counters={'luid_0x00000000_0x0000F112_phys_0':0,
                  'luid_0x00000000_0x0049310D_phys_0':1200000000}
        self.assertEqual(list(adapter_values(counters,'luid_0x00000000_0x0049310d').values()),[1200000000])
        self.assertEqual(adapter_values(counters,None),{})
    def test_driver_board_power_and_sensor_units(self):
        from serve.amd_sensors import Reader
        reader=Reader.__new__(Reader)
        reader.adapter=0;reader.context=None
        def query(context,adapter,pointer):
            for sensor,value in ((8,33),(27,40),(9,60),(21,698),(23,40),(73,92)):
                pointer._obj.sensors[sensor].supported=1
                pointer._obj.sensors[sensor].value=value
            return 0
        reader.query=query
        data=reader.read()
        self.assertEqual(data['power'],92)  # board power, not ASIC power
        self.assertEqual(data['temp_hotspot'],40)
        self.assertAlmostEqual(data['volt'],.698)

if __name__ == '__main__':
    unittest.main()
