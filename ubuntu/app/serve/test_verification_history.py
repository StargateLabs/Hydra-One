import json
import tempfile
import unittest
from pathlib import Path
from serve.verification_history import verification_history


class HistoryTests(unittest.TestCase):
    def test_real_proofs_require_explicit_success_and_no_gpu_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'output/verification';folder.mkdir(parents=True)
            path=folder/'gguf-parts-cpu-real.json'
            proof=dict(greedy_response_equal=False,gpu_used=False,parts=['a','b'])
            path.write_text(json.dumps(proof));self.assertEqual(verification_history(root),[])
            proof['greedy_response_equal']=True;path.write_text(json.dumps(proof))
            rows=verification_history(root);self.assertEqual(len(rows),1);self.assertIsNone(rows[0]['seconds'])
            self.assertEqual(rows[0]['kind'],'functional_evidence')
    def test_deduplicates_reports_and_preserves_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'output/verification';run=folder/'server-suite-isolated-one';run.mkdir(parents=True)
            log=run/'server-suite.log';log.write_text('fixture')
            report=dict(log=str(log),exit_code=124,seconds=240,completed_at=1)
            (run/'server-suite.json').write_text(json.dumps(report))
            (folder/'server-isolated-current.json').write_text(json.dumps(report))
            rows=verification_history(root);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'failed')
            self.assertNotIn('tok_s',rows[0])

    def test_rejects_foreign_log_and_invalid_outcome(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'output/verification';folder.mkdir(parents=True)
            outside=root/'foreign.log';outside.write_text('fixture')
            path=folder/'server-isolated-current.json'
            path.write_text(json.dumps(dict(log=str(outside),exit_code=0,seconds=1)))
            self.assertEqual(verification_history(root),[])
            log=folder/'local.log';log.write_text('fixture')
            path.write_text(json.dumps(dict(log=str(log),exit_code=True,seconds=1)))
            self.assertEqual(verification_history(root),[])
