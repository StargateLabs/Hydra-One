import unittest
from serve.instrumentation import active_instrumentation
class Instrumentation(unittest.TestCase):
 def test_colibri_retains_native_identity_and_no_external_api_notice(self):
  row=active_instrumentation({}, {'status':'ready','mode':'api','publisher':'colibri','public_model':'local/qwen3.6-colibri'}, {})
  self.assertEqual(row['source'],'colibri');self.assertEqual(row['backend'],'Colibri');self.assertEqual(row['limits'],[])
 def test_shared_functions_follow_every_engine(self):
  for mode in ('gguf','safetensors','api'):
   row=active_instrumentation({'model':'native'}, {'status':'ready','mode':mode,'public_model':'local/test','backend':mode,'capabilities':{'tool_calling':False}}, {'cpu':0,'ram_used':1})
   self.assertEqual(row['source'],'optional');self.assertEqual(row['model'],'local/test');self.assertTrue(all(row['functions'].values()));self.assertTrue(row['hardware_sensors_available']);self.assertFalse(row['tool_calling']);self.assertTrue(row['limits'])
 def test_stopped_optional_restores_native_identity(self):
  row=active_instrumentation({'model':'native','backend':'hip'}, {'status':'idle','model':'old'}, {})
  self.assertEqual(row['model'],'native');self.assertEqual(row['backend'],'hip');self.assertFalse(row['hardware_sensors_available'])
