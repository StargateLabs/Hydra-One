"""Software-only proof that the shared benchmark retains HYDRA identity."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from serve.optional_benchmark import OptionalBenchmark
from serve.test_optional_benchmark_stream import Manager


class HydraBenchmarkTests(unittest.TestCase):
    def test_shared_streaming_benchmark_persists_hydra_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(Path(directory))
            state={**manager.status(), 'backend':'HYDRA ONE',
                   'engine_addon':'hydra-one','verification_fixture':True,
                   'hydra':{'mode':'embedded','adaptive_routing':False}}
            manager.status=lambda:state
            benchmark=OptionalBenchmark(manager)
            with patch('serve.optional_benchmark.threading.Thread'):
                benchmark.start(dict(runs=3,tokens=32,stream=True,prompt='hello'))
            benchmark._run(state,'hello',False)
            job=benchmark.status()[0]
            self.assertEqual(job['status'],'complete')
            self.assertEqual(job['configuration']['engine_addon'],'hydra-one')
            self.assertEqual(len(job['configuration']['hydra_bundle_sha256']),64)
            report=json.loads(next((Path(directory)/'data/benchmark-checks').glob('*.json')).read_text())
            self.assertEqual(report['backend'],'HYDRA ONE')
            self.assertTrue(report['verification_fixture'])
            self.assertEqual(report['protocol']['configuration'],job['configuration'])
            self.assertEqual(len(manager.requests),4)
            self.assertTrue(all(request['stream'] for request in manager.requests))
            self.assertIsNone(job['sample_series'][1]['decode_tok_s'])
            self.assertGreater(job['sample_series'][1]['ttft_s'],0)
            self.assertFalse(manager.conversation_lock.locked())

    def test_running_chat_blocks_benchmark(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=Manager(Path(directory))
            manager.conversation_lock.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    OptionalBenchmark(manager).start(dict(runs=3,tokens=32))
                self.assertEqual(manager.requests,[])
            finally:manager.conversation_lock.release()
