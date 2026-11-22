"""Advanced TRL checkpoint save/resume: capability is reachable and honoured."""
import ast,json,tempfile,unittest
from pathlib import Path
from serve.training_options import training_options

ROOT=Path(__file__).resolve().parents[1]
RUNNER=ROOT/'tools/train_trl_advanced.py'

class AdvancedCheckpointTests(unittest.TestCase):
  def options(self,**changes):
    return training_options({'method':'dpo',**changes})

  def test_save_and_resume_are_reachable_for_advanced_methods(self):
    for method in ('dpo','grpo','kto','reward'):
      for payload in ({'save_steps':1},{'resume_checkpoint':'output/training/run/trainer/checkpoint-1'}):
        with self.subTest(method=method,payload=payload):
          self.assertEqual(training_options({'method':method,**payload})[list(payload)[0]],list(payload.values())[0])

  def test_layer_streaming_stays_rejected_for_advanced_methods(self):
    for bad in ({'runner':'soup_native'},{'device':'cuda'},{'layer_streaming':True}):
      with self.subTest(payload=bad):
        with self.assertRaises(ValueError):training_options({'method':'kto',**bad})

  def test_runner_accepts_and_uses_the_checkpoint_flags(self):
    """The declared flags must reach the trainer, not stop at argparse."""
    import subprocess,sys
    completed=subprocess.run([sys.executable,str(RUNNER),'--help'],capture_output=True,text=True,timeout=180)
    self.assertEqual(completed.returncode,0,completed.stderr)
    for flag in ('--save-steps','--resume-checkpoint','--checkpointing','--method'):
      with self.subTest(flag=flag):self.assertIn(flag,completed.stdout)
    source=ast.parse(RUNNER.read_text(encoding='utf-8'))
    # Resume must be passed to Trainer.train; save must reach the config.
    train=next(call for call in ast.walk(source)
      if isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='train')
    self.assertTrue(any(isinstance(kw.value,ast.IfExp) for kw in train.keywords),
      'trainer.train must accept resume_from_checkpoint')
    save=next(kw for node in ast.walk(source)
      if isinstance(node,ast.Call) for kw in node.keywords if kw.arg=='save_strategy')
    self.assertIsInstance(save.value,ast.IfExp,'save_strategy must follow --save-steps')

  def test_checkpoint_is_recorded_for_the_resume_button(self):
    source=RUNNER.read_text(encoding='utf-8')
    self.assertIn("report['checkpoint']",source,'the workflow report must expose the saved checkpoint')

  def test_resume_is_validated_before_the_trainer_starts(self):
    source=RUNNER.read_text(encoding='utf-8')
    self.assertIn('validate_checkpoint',source,'an incompatible resume must be rejected before training')
    self.assertRegex(source,r'validate_checkpoint\((?:[^()\n]*|\([^()\n]*\))*\)')

  def test_resume_options_match_the_validated_control_surface(self):
    """The dashboard must be able to send what the runner now honours."""
    accepted=training_options({'method':'dpo','save_steps':4,'steps':8})
    self.assertEqual(accepted['save_steps'],4)
    self.assertEqual(accepted['steps'],8)

if __name__=='__main__':unittest.main()
