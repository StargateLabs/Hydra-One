import unittest
from serve.runtime_updates import select_node_release, version_state


class RuntimeUpdates(unittest.TestCase):
    def test_node_preserves_major_and_ignores_preview(self):
        releases=[{'version':'v26.0.0'}, {'version':'v24.20.0-rc.1'},
                  {'version':'v24.20.0'}, {'version':'v24.19.0'}]
        self.assertEqual(select_node_release(releases,'24.19.0')['version'],'v24.20.0')

    def test_installed_newer_is_not_an_update(self):
        self.assertEqual(version_state('3.12.11','3.12.10'),'ahead')
        self.assertEqual(version_state('3.12.10','3.12.11'),'available')
        self.assertEqual(version_state('3.12.10',None),'unavailable')

    def test_bad_source_does_not_claim_current(self):
        self.assertEqual(version_state('unknown','1.0.0'),'unavailable')
