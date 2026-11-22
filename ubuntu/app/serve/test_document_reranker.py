import unittest,tempfile,json
from pathlib import Path
from serve.document_reranker import model,ranked
class Reranker(unittest.TestCase):
 def test_unprepared_model_refused(self):
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as d:
   with self.assertRaises(ValueError):model(Path(d))
 def test_scores_reorder_but_keep_source_identity(self):
  rows=[{'chunk':3,'text':'a','page':1},{'chunk':8,'text':'b','page':4}]
  out=ranked(rows,[.2,.9]);self.assertEqual(out[0]['chunk'],8);self.assertEqual(out[0]['page'],4);self.assertNotIn('rerank_score',rows[0])
 def test_invalid_scores_refused(self):
  for scores in ([float('nan')],[],['x']):
   with self.assertRaises(ValueError):ranked([{'text':'a'}],scores)
if __name__=='__main__':unittest.main()
