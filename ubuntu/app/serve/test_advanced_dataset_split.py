import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from serve.local_training import LocalTraining
class AdvancedSplit(unittest.TestCase):
 def test_split_preserves_preference_and_reward_fields(self):
  for method in ('dpo','grpo'):
   with self.subTest(method=method),tempfile.TemporaryDirectory() as directory:
    root=Path(directory);folder=root/'output/training-datasets';folder.mkdir(parents=True)
    rows=[{'prompt':str(i),'chosen':'yes','rejected':'no'} if method=='dpo' else {'prompt':str(i),'target':'yes'} for i in range(4)]
    source=folder/'source.jsonl';source.write_text('\n'.join(json.dumps(row) for row in rows))
    training=LocalTraining(SimpleNamespace(root=root));result=training.split_dataset({'path':str(source)})
    output=[]
    for kind in ('train','validation'):output += [json.loads(line) for line in Path(result['datasets'][kind]['path']).read_text().splitlines()]
    self.assertEqual(sorted(output,key=lambda row:row['prompt']),rows)
    self.assertFalse(any('text' in row for row in output));self.assertFalse(result['overlap'])

 def test_kto_split_keeps_both_classes_and_boolean_labels(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);folder=root/'output/training-datasets';folder.mkdir(parents=True)
   rows=[{'prompt':str(i),'completion':'Answer '+str(i),'label':i%2==0} for i in range(8)]
   source=folder/'source.jsonl';source.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8')
   result=LocalTraining(SimpleNamespace(root=root)).split_dataset({'path':str(source)})
   for kind in ('train','validation'):
    selected=[json.loads(line) for line in Path(result['datasets'][kind]['path']).read_text(encoding='utf-8').splitlines()]
    self.assertEqual({row['label'] for row in selected},{True,False})
   self.assertFalse(result['overlap'])
