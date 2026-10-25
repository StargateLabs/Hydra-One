import unittest
from serve.benchmark_state import merge_benchmark_state

class BenchmarkStateTests(unittest.TestCase):
    def test_completed_current_job_is_visible_before_history_write(self):
        job=dict(id='new',status='complete',started_at=2,model='local/a',completed_samples=6,results=[dict(samples=5)])
        merged=merge_benchmark_state(dict(job=dict(status='idle'),history=[]),job,[],'local/a')
        self.assertEqual(merged['job']['completed_samples'],6)
    def test_completed_optional_run_replaces_old_native_failure_when_unloaded(self):
        old=dict(id='old',status='failed',started_at=1,model='strata')
        new=dict(id='new',status='complete',started_at=2,model='local/model')
        merged=merge_benchmark_state(dict(job=old,history=[old]),dict(status='idle'),[new])
        self.assertEqual(merged['job']['id'],'new');self.assertEqual([r['id'] for r in merged['history']],['new','old'])
    def test_active_run_cannot_be_replaced_by_completed_history(self):
        live=dict(id='live',status='running',started_at=1)
        merged=merge_benchmark_state(dict(job=live,history=[]),dict(status='idle'),[dict(id='later',status='complete',started_at=2)])
        self.assertEqual(merged['job']['id'],'live')
    def test_ready_model_selects_its_own_report_and_history_is_deduplicated(self):
        first=dict(id='a',model='local/a',status='complete',started_at=1)
        second=dict(id='b',model='local/b',status='complete',started_at=2)
        merged=merge_benchmark_state(dict(job=second,history=[first]),dict(status='idle'),[first,second],'local/a')
        self.assertEqual(merged['job']['id'],'a');self.assertEqual(len(merged['history']),2)
