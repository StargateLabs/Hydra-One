import unittest
from serve.hydra_lab_app import require_completed_task,TaskIncomplete
class TaskCompletionTests(unittest.TestCase):
 def test_script_entrypoint_uses_same_exception_identity(self):
  import importlib.util
  from pathlib import Path
  spec=importlib.util.spec_from_file_location('alternate_lab_entry',Path(__file__).with_name('hydra_lab_app.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  self.assertIs(module.TaskIncomplete,TaskIncomplete)
 def test_budget_exhaustion_preserves_response(self):
  response={'choices':[{'finish_reason':'length','message':{'content':'Il'}}]}
  with self.assertRaises(TaskIncomplete) as caught:require_completed_task(response)
  self.assertIs(caught.exception.response,response)
 def test_reasoning_without_answer_is_incomplete(self):
  with self.assertRaises(TaskIncomplete):require_completed_task({'choices':[{'finish_reason':'stop','message':{'content':'','reasoning_content':'reasoning'}}]})
 def test_completed_answer_passes(self):
  require_completed_task({'choices':[{'finish_reason':'stop','message':{'content':'7'}}]})
