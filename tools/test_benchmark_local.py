import tempfile
from pathlib import Path
import unittest
from tools.benchmark_local import new_timings, summarize


class BenchmarkTests(unittest.TestCase):
    def test_log_truncation_invalidates_arm(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"engine.log"
            p.write_bytes(b"previous log bytes")
            st = p.stat()
            p.write_bytes(b"")
            with self.assertRaises(RuntimeError):
                new_timings(p,st.st_size,(st.st_dev,st.st_ino))

    def test_warmup_excluded_and_even_median(self):
        rows = [dict(warmup=w,decode_tok_s=v,prefill_tok_s=v,wall_tok_s=v,wall_s=v)
                for w,v in ((True,9999),(False,10),(False,20))]
        self.assertEqual(summarize(rows)["decode_tok_s"],dict(median=15,min=10,max=20,n=2))


if __name__ == "__main__":
    unittest.main()
