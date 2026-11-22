import json,tempfile,unittest
from unittest.mock import patch
from serve.transformers_compatibility import latest,cached

class CompatibleReleaseTests(unittest.TestCase):
 def test_newest_compatible_stable_release_and_cache(self):
  metadata={'info':{'name':'transformers','version':'5.19.0'},'urls':[],'releases':{'5.17.0':[{'yanked':False}],'5.18.0':[{'yanked':False}],'5.19.0':[{'yanked':False}],'5.17.1':[{'yanked':True}],'5.17.2rc1':[{'yanked':False}]}}
  selected={'info':{'name':'transformers','version':'5.17.0'},'urls':[]}
  class Response:
   def __init__(self,data):self.data=data
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,*args):return json.dumps(self.data).encode()
  with tempfile.TemporaryDirectory() as folder,patch('serve.transformers_compatibility.constraints',return_value=(['>=4.52.4,<=5.17.0'],'current')),patch('serve.transformers_compatibility.urlopen',side_effect=[Response(metadata),Response(selected)]):
   result=latest(folder)
   self.assertEqual(result['version'],'5.17.0');self.assertEqual(result['latest_version'],'5.19.0')
   self.assertEqual(cached(folder,{'version':'5.19.0'})['version'],'5.17.0')
   with patch('serve.transformers_compatibility.constraints',return_value=(['<=5.19.0'],'changed')):
    self.assertFalse(cached(folder,result)['compatible_release'])
