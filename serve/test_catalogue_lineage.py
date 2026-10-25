import unittest
from unittest.mock import patch
from serve.optional_catalogue import base_identity,upstream_identity

class LineageTests(unittest.TestCase):
 def test_intermediate_author_is_preserved_and_cycle_is_bounded(self):
  upstream_identity.cache_clear()
  self.addCleanup(upstream_identity.cache_clear)
  def info(url):
   repo=url.split('/api/models/')[1]
   return {'cardData':{'base_model':{'community/tuned':'official/base','official/base':'community/tuned'}[repo]}}
  with patch('serve.optional_catalogue.get_json',side_effect=info),patch('serve.optional_catalogue.publisher_icon',return_value='official-icon') as icon:
   result=base_identity({'cardData':{'base_model':'community/tuned'}})
  self.assertEqual(result['derived_from'],'community/tuned')
  self.assertEqual(result['lineage'],['community/tuned','official/base'])

if __name__=='__main__':unittest.main()

class DeclaredBasesTests(unittest.TestCase):
 def test_merge_preserves_all_valid_unique_sources(self):
  from serve.optional_catalogue import declared_bases
  self.assertEqual(declared_bases({'cardData':{'base_model':['a/model','b/model','a/model',None,'https://invalid','../bad']}}),['a/model','b/model'])
 def test_bad_card_is_empty(self):
  from serve.optional_catalogue import declared_bases
  self.assertEqual(declared_bases({'cardData':[]}),[])
