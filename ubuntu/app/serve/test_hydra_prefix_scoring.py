import unittest
from serve.hydra_prefix_scoring import prefix_request
class PrefixScoringTests(unittest.TestCase):
 def test_exact_bytes_and_explicit_separator(self):
  body=dict(prefix_text='  e\u0301\r\nAnswer:',alternatives=[dict(id='a',text=' yes'),dict(id='b',text=' no')],separator='exact',normalize='sum')
  request,identity=prefix_request(body)
  self.assertEqual(request['prefix_text'],body['prefix_text']);self.assertEqual(request['alternatives'],body['alternatives'])
  self.assertEqual(identity['prefix_utf8_hex'],body['prefix_text'].encode().hex())
  body['separator']='space';request,_=prefix_request(body);self.assertEqual(request['alternatives'][0]['text'],'  yes')
 def test_invalid_separator_and_duplicate_ids_are_rejected(self):
  for body in (dict(prefix_text='x',alternatives=[dict(id='a',text='y')],separator='trim'),dict(prefix_text='x',alternatives=[dict(id='a',text='y'),dict(id='a',text='z')])):
   with self.assertRaises(ValueError):prefix_request(body)
