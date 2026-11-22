import unittest
from serve.optional_catalogue import model_card_sections
class CardSectionsTests(unittest.TestCase):
 def test_source_and_code(self):
  text='# Changes\nOriginal claim\n```\n# not a heading\n```\n## Limitations\nCannot process audio'
  rows=model_card_sections(text)
  self.assertEqual([r['title'] for r in rows],['Changes','Limitations']);self.assertIn('# not a heading',rows[0]['text']);self.assertEqual(rows[1]['text'],'Cannot process audio')
 def test_bounded_and_empty(self):
  self.assertEqual(model_card_sections(None),[]);self.assertEqual(model_card_sections('# Empty'),[]);self.assertEqual(len(model_card_sections('# Heading\n'+'x'*9000)[0]['text']),4000)
if __name__=='__main__':unittest.main()

class AuthorMetadataTests(unittest.TestCase):
 def test_declared_only(self):
  from serve.optional_catalogue import author_metadata
  self.assertEqual(author_metadata({'cardData':{'language':['it','en','it',42],'datasets':'org/data','library_name':'transformers','invented':'fast'}}),{'language':['it','en'],'datasets':['org/data'],'library_name':['transformers']})
 def test_missing_and_bounded(self):
  from serve.optional_catalogue import author_metadata
  self.assertEqual(author_metadata({'cardData':[]}),{})
  self.assertEqual(len(author_metadata({'cardData':{'license_name':'x'*300}})['license_name'][0]),200)
