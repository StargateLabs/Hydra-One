import unittest
from unittest.mock import patch
from types import SimpleNamespace
from serve.telemetry import _AmdWindows as AmdReader


class CpuPowerSensorTests(unittest.TestCase):
    """The Monitor's "Potenza CPU" tile reads AIDA64's CPU Package id: the stable one on this PC."""

    def _read(self, sensors):
        reader = AmdReader.__new__(AmdReader)
        reader.pdh = SimpleNamespace(PdhCollectQueryData=lambda *a: None)
        reader._q_util = reader._q_mem = reader._q_tc = object()
        reader._h_util = reader._h_mem = None
        reader._array = lambda handle: {}
        reader._vram_total = None
        reader._amd_index = 0
        reader._aida_read = lambda: sensors
        reader._sensor_reader = SimpleNamespace(read=lambda: {})
        with patch('serve.pcie_link.start', lambda: None), patch('serve.pcie_link.current', lambda: None):
            return reader.read()

    def test_prefers_the_stable_aida_package_power(self):
        # PCPU is sampled but unreadable on this build: 10..303 W with no relation to the load.
        sensors = {"TCPUPKG": "48", "PCPU": "10.23", "PCPUPKG": "114.56", "PCPUIAC": "100.08"}
        out = self._read(sensors)
        self.assertEqual(out["cpu_power"], 114.56)
        self.assertEqual(out["cpu_temp"], 48.0)

    def test_falls_back_to_cpu_power_when_package_is_missing(self):
        out = self._read({"TCPUPKG": "48", "PCPU": "42.78"})
        self.assertEqual(out["cpu_power"], 42.78)

    def test_no_cpu_power_sensor_leaves_the_tile_empty_instead_of_zero(self):
        out = self._read({"TCPUPKG": "48"})
        self.assertNotIn("cpu_power", out)


if __name__ == '__main__':
    unittest.main()