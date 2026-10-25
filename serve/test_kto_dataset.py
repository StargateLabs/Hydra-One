import json,tempfile,unittest
from pathlib import Path
from tools.train_local_lora import dataset_rows
from serve.training_options import training_options
class KTODataset(unittest.TestCase):
 def test_boolean_preferences_are_preserved_and_inferred(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'kto.jsonl';rows=[{'prompt':'Hello','completion':'Hi','label':True},{'prompt':'Question','completion':'Wrong','label':False}]
   path.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
   for method in ('auto','kto'):
    actual=dataset_rows(path,method);self.assertIs(actual[0]['label'],True);self.assertIs(actual[1]['label'],False)
   self.assertEqual(training_options({'method':'kto'})['method'],'kto')
 def test_string_labels_are_rejected(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'kto.jsonl';path.write_text(json.dumps({'prompt':'a','completion':'b','label':'true'}),encoding='utf-8')
   with self.assertRaises(ValueError):dataset_rows(path,'kto')
