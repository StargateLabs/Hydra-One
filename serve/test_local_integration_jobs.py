import unittest
from unittest.mock import patch
from serve.local_integration_jobs import AirLLMSetup,OpenWebUISetup


class SetupTests(unittest.TestCase):
    def test_busy_system_does_not_start_installer(self):
        setup=AirLLMSetup('.',lambda:False)
        with patch('serve.local_integration_jobs.threading.Thread') as thread:
            with self.assertRaises(ValueError):setup.prepare()
            thread.assert_not_called()

    def test_second_preparation_is_rejected(self):
        setup=AirLLMSetup('.',lambda:True)
        setup.job={'state':'preparing'}
        with self.assertRaises(ValueError):setup.prepare()

    def test_failure_is_terminal_and_recorded(self):
        setup=AirLLMSetup('.',lambda:True)
        with patch('serve.airllm_runtime.prepare',side_effect=ValueError('package unavailable')):
            setup._prepare(None)
        self.assertEqual(setup.job['state'],'error')
        self.assertIn('package unavailable',setup.job['error'])


class OpenWebUISetupTests(unittest.TestCase):
    def test_busy_machine_does_not_launch_installer(self):
        setup=OpenWebUISetup('.',lambda:False)
        with patch('serve.local_integration_jobs.threading.Thread') as thread:
            with self.assertRaises(ValueError):setup.prepare()
            thread.assert_not_called()

    def test_preparing_request_reports_pending_even_with_previous_shared_job(self):
        setup=OpenWebUISetup('.',lambda:True);setup.job={'state':'preparing'}
        with patch('serve.open_webui_runtime.status',return_value={'job':{'state':'prepared'},'setup_busy':False,'busy':False}):
            self.assertEqual(setup.status()['job']['state'],'preparing')

    def test_setup_failure_does_not_claim_prepared(self):
        setup=OpenWebUISetup('.',lambda:True)
        with patch('serve.open_webui_runtime.prepare',side_effect=ValueError('package unavailable')):setup._prepare(None)
        self.assertEqual(setup.job['state'],'error');self.assertIn('package unavailable',setup.job['error'])
