import unittest
from tools.analyze_decode_budget import analyze,gpu_stages

LINE='strata decode timing: 100 windows, avg T 3.00, 2.00 tokens/window, 40.00 ms/window = verify 30.00 (GPU-reach wait 20.00 + per-layer host 8.00 [plan 0.10 actq 0.20 jobs 3.00 CPU 4.00] + stage 0.01) + commit/emit 0.20 + draft 4.00'

class DecodeBudgetTests(unittest.TestCase):
    def test_gpu_stages_keep_waits_separate_and_skip_warmup(self):
        line='strata decode GPU stages (ms/window): GDN layers: q8+qkv/q-idx gemv 1.00 waitA 2.00 VRAM hits 3.00 | QSA layers: attention 4.00 waitCPU 5.00 | total 15.00 ms/window over 100 windows'
        result=gpu_stages(line+'\n'+line.replace('waitA 2.00','waitA 7.00'),1)
        self.assertEqual(result['measured_requests'],1)
        self.assertEqual(result['median_ms_per_window']['gdn:waitA'],7)
        self.assertEqual(result['median_ms_per_window']['qsa:attention'],4)
        self.assertNotIn('qsa:total',result['median_ms_per_window'])
    def test_measured_budget_excludes_warmup_and_does_not_sum_nested_timers(self):
        result=analyze(LINE.replace('40.00 ms/window','99.00 ms/window')+'\n'+LINE,warmup=1)
        self.assertEqual(result['measured_requests'],1)
        self.assertEqual(result['medians']['target_window_ms'],20)
        self.assertEqual(result['medians']['window_reduction_required_percent'],50)
        self.assertEqual(result['medians']['host_ms'],8)
    def test_empty_or_incomplete_logs_are_not_evidence(self):
        with self.assertRaises(ValueError):analyze('cancelled request',0)
        with self.assertRaises(ValueError):analyze(LINE,1)
    def test_single_phase_elimination_does_not_promise_the_target(self):
        result=analyze(LINE,0)
        host=result['single_phase_elimination']['host_ms']
        self.assertEqual(host['median_optimistic_decode_tok_s'],62.5)
        self.assertFalse(host['all_requests_reach_target'])
        self.assertEqual(result['medians']['tokens_required_at_current_latency'],4)
    def test_invalid_target_and_warmup_are_rejected(self):
        for target in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):analyze(LINE,0,target)
        with self.assertRaises(ValueError):analyze(LINE,-1)
