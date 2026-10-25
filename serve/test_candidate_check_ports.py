"""The candidate check reads the dashboard that is actually running, not a fixed port."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'tools' / 'verify_strata_release_bounded.py'


class CandidateCheckPortTests(unittest.TestCase):
    def source(self):
        return RUNNER.read_text(encoding='utf-8')

    def test_no_dashboard_port_is_hardcoded(self):
        source = self.source()
        for port in ('8088', '8090'):
            with self.subTest(port=port):
                self.assertNotIn("call(%s," % port, source,
                                 f'the candidate check must not depend on port {port}')

    def test_the_running_dashboard_port_is_discovered(self):
        source = self.source()
        self.assertIn('def dashboard_port', source,
                      'the running dashboard port must be discovered, not assumed')

    def test_the_discovered_port_is_used_for_the_idle_check(self):
        source = self.source()
        self.assertIn('port=dashboard_port()', source)
        self.assertIn("call(port,'/metrics')", source)
        self.assertIn("call(port,'/config')", source)

    def test_a_silent_dashboard_is_reported_not_crashed(self):
        """No dashboard at all must be a clear error, not a connection traceback."""
        source = self.source()
        self.assertIn('no Strata dashboard', source,
                      'a missing dashboard must produce an explicit message')


if __name__ == '__main__':
    unittest.main()
