import json
from pathlib import Path
import tempfile
import unittest
from tools.unsloth_preflight import validate_corpus

class CorpusTests(unittest.TestCase):
    def test_split_leakage_and_missing_language_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'corpus.jsonl'
            rows=[dict(conversation_id=f'{split}-{language}',split=split,language=language,messages=[dict(role='user',content=f'hello-{split}-{language}'),dict(role='assistant',content='ciao')]) for split in ('train','validation','held_out') for language in ('it','en')]
            path.write_text('\n'.join(map(json.dumps,rows)),encoding='utf-8')
            self.assertEqual(validate_corpus(path),dict(train=2,validation=2,held_out=2))
            rows[-1]['conversation_id']=rows[0]['conversation_id']
            path.write_text('\n'.join(map(json.dumps,rows)),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'repeated'):validate_corpus(path)
            rows[-1]['conversation_id']='new-id';rows[-1]['messages']=rows[0]['messages']
            path.write_text('\n'.join(map(json.dumps,rows)),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'leaks'):validate_corpus(path)

if __name__=='__main__':unittest.main()
