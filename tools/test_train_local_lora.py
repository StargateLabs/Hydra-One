import tempfile,unittest,json
from pathlib import Path
from tools.train_local_lora import dataset_rows,validate_destination,ROOT

class TrainingValidation(unittest.TestCase):
    def test_conversations_validate_turns_and_canonical_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'data.jsonl'
            messages=[{'role':'user','content':'Hello'},{'role':'assistant','content':'Hi'}]
            p.write_text(json.dumps({'messages':messages}),encoding='utf-8')
            row=dataset_rows(p)[0];self.assertEqual(row['messages'],messages)
            self.assertEqual(json.loads(row['text']),messages)
            for invalid in ([messages[0]],list(reversed(messages)),[{'role':'tool','content':'x'},messages[1]]):
                p.write_text(json.dumps({'messages':invalid}),encoding='utf-8')
                with self.assertRaises(ValueError):dataset_rows(p)
    def test_loss_template_requires_known_markup(self):
        from types import SimpleNamespace
        from tools.train_local_lora import assistant_template
        with self.assertRaises(ValueError):assistant_template(SimpleNamespace(chat_template='unknown'))
        template='{% generation %}{{message}}{% endgeneration %}'
        self.assertEqual(assistant_template(SimpleNamespace(chat_template=template)),template)
    def test_malformed_or_empty_dataset_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'data.jsonl'
            for value in ('',json.dumps({'text':''}),json.dumps({'text':'hello','extra':1})):
                p.write_text(value)
                with self.assertRaises(ValueError):dataset_rows(p)
            p.write_text(json.dumps({'text':'hello world'}))
            self.assertEqual(dataset_rows(p),[{'text':'hello world'}])
    def test_existing_or_external_output_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):validate_destination(directory,directory)
            with self.assertRaises(ValueError):validate_destination(directory,Path(directory)/'new')

if __name__=='__main__':unittest.main()
