"""Recovery admission must remain narrow and must not add hidden generations."""
import unittest
from serve import hydra_fastpath
from serve.hydra_lab_benchmarks import validate_runner_request


class RecoveryTests(unittest.TestCase):
    def test_explicit_recovery_request_has_no_warmup(self):
        from serve.hydra_gpu_recovery_v16 import request_indices
        self.assertEqual(list(request_indices(1)), [1])
        self.assertEqual(list(request_indices(3)), [1, 2, 3])
        with self.assertRaises(ValueError):
            list(request_indices(2))

    def test_historical_gpu_remains_quarantined(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'marker'; marker.write_text('protected')
            with self.assertRaises(ValueError):
                hydra_fastpath.guard_safety({'layers': 29}, marker)

    def test_no_recovery_without_explicit_session_grant(self):
        from serve.hydra_gpu_recovery_v16 import load_grant
        from unittest.mock import patch
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ValueError):
                load_grant()

    def test_frozen_body_rejects_other_model_or_larger_output(self):
        from serve.hydra_gpu_recovery_v16 import validate_body, PROMPT, PROFILE
        body = dict(profile=PROFILE, model_id=hydra_fastpath.QWEN, prompt=PROMPT,
                    prompt_id='v16-first', samples=1, max_tokens=8)
        validate_body(body, {'samples': 1})
        for key, value in [('max_tokens', 16), ('samples', 3), ('model_id', 'other'), ('prompt', 'other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_body(dict(body, **{key: value}), {'samples': 1})

    def test_module_capture_preserves_append_only_identity_event(self):
        import tempfile
        from pathlib import Path
        from serve.hydra_lab_benchmarks import Registry
        from serve.hydra_gpu_recovery_v16 import persist_module_evidence
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); store=Registry(folder/'registry')
            identity={'pid':123,'loaded_DLL_map':'NOT_AVAILABLE'}
            row=dict(run_id='fixture',timestamp='2026-10-19T00:00:00+00:00',
                     status='RUNNING',process_identity=identity,
                     events=[dict(kind='owned_process_identity',detail=identity)])
            store.put(row)
            persist_module_evidence(row,[],folder)
            row['events'].append(dict(kind='ready'))
            store.put(row)
            saved=store.get('fixture')
            self.assertEqual(saved['events'][0]['detail']['loaded_DLL_map'],'NOT_AVAILABLE')
            self.assertEqual(saved['process_identity']['loaded_DLL_map'],[])
            self.assertTrue((folder/'loaded-modules.json').is_file())


if __name__ == '__main__':
    unittest.main()
