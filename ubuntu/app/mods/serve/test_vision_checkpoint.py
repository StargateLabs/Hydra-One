"""Vision training must save and resume like the other runners."""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

from serve.training_options import training_options

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'tools' / 'train_vlm_lora.py'


class VisionCheckpointTests(unittest.TestCase):
    def test_save_and_resume_are_reachable_from_the_dashboard(self):
        for payload in ({'save_steps': 1}, {'resume_checkpoint': 'output/training/run/trainer/checkpoint-1'}):
            with self.subTest(payload=payload):
                self.assertTrue(training_options({'method': 'vlm', **payload}))

    def test_gpu_is_still_rejected_for_vision(self):
        with self.assertRaises(ValueError):
            training_options({'method': 'vlm', 'device': 'cuda'})

    def test_runner_declares_and_uses_the_checkpoint_flags(self):
        completed = subprocess.run([sys.executable, str(RUNNER), '--help'],
                                   capture_output=True, text=True, timeout=180)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for flag in ('--save-steps', '--resume-checkpoint'):
            with self.subTest(flag=flag):
                self.assertIn(flag, completed.stdout)

    def test_checkpoint_files_match_the_shared_resume_contract(self):
        """validate_checkpoint reads these names; the vision runner must write them."""
        source = RUNNER.read_text(encoding='utf-8')
        for name in ('optimizer.pt', 'scheduler.pt', 'rng_state.pth',
                     'adapter_config.json', 'adapter_model.safetensors', 'trainer_state.json'):
            with self.subTest(name=name):
                self.assertIn(name, source, f'vision checkpoint is missing {name}')

    def test_resume_is_validated_before_the_loop_starts(self):
        source = RUNNER.read_text(encoding='utf-8')
        self.assertIn('validate_checkpoint', source)
        # the resume must be resolved before the training loop is entered
        validate_at = source.index('validate_checkpoint')
        loop_at = source.index('for step in range(')
        self.assertLess(validate_at, loop_at, 'resume is validated after training started')

    def test_checkpoint_path_is_reported_for_the_resume_button(self):
        source = RUNNER.read_text(encoding='utf-8')
        self.assertIn("report['checkpoint']", source)

    def test_checkpoint_only_on_requested_steps(self):
        source = RUNNER.read_text(encoding='utf-8')
        self.assertIn('a.save_steps', source, 'checkpoint saving is not gated on --save-steps')


if __name__ == '__main__':
    unittest.main()
