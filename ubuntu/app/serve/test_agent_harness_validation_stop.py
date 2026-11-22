import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from serve.agent_harness import AgentHarness


class ValidationStop(unittest.TestCase):
    def _probe(self, validation):
        return AgentHarness(Path(tempfile.gettempdir()) / 'strata-harness-stop-fixture',
                            kind='hermes', validation=validation)

    def test_validation_probe_stops_even_when_activity_is_unknown(self):
        probe = self._probe(True)
        with patch('serve.harness_activity.activity', return_value={'busy': True}), \
                patch.object(probe, '_stop_child') as stop_child, patch.object(probe, '_release'):
            probe.stop()
        stop_child.assert_called_once()

    def test_user_harness_still_refuses_to_stop_with_unknown_activity(self):
        probe = self._probe(False)
        with patch('serve.harness_activity.activity', return_value={'busy': True}):
            with self.assertRaises(RuntimeError):
                probe.stop()


if __name__ == '__main__':
    unittest.main()
