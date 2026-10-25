import unittest
from benchmark_guard import require_completed, require_run_result, require_startup_vram_margin

class GuardTests(unittest.TestCase):
    def test_startup_margin_stops_low_or_invalid_readings(self):
        self.assertEqual(require_startup_vram_margin({'vram_free_mib':1536}),1536)
        for value in (None,37,1535,True,'2048',float('nan'),float('inf')):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                require_startup_vram_margin({'vram_free_mib':value})
    def test_harness_tuple_and_failure_stop(self):
        record = dict(completion_tokens=1, answer_head='42', engine_decode_tps=20.0)
        self.assertEqual(require_run_result((record, 123)), (record, 123))
        with self.assertRaises(RuntimeError):
            require_run_result(({'error':'GPU failure'}, 123))
    def test_real_measurement(self):
        record = dict(completion_tokens=256, answer_head='Answer', engine_decode_tps=54.0)
        self.assertIs(require_completed(record), record)

    def test_invalid_results_stop_immediately(self):
        good = dict(completion_tokens=256, answer_head='Answer', engine_decode_tps=54.0)
        for changes in ({'error':'GPU reset'}, {'completion_tokens':0}, {'answer_head':''},
                        {'engine_decode_tps':None}, {'engine_decode_tps':float('nan')},
                        {'engine_decode_tps':float('inf')}, {'completion_tokens':True}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                require_completed({**good, **changes})

if __name__ == '__main__':
    unittest.main()
