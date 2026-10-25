import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from serve.optional_catalogue import OptionalCatalogue
class CardCacheTests(unittest.TestCase):
 def test_variants_share_card_revision_changes_and_limit(self):
  with tempfile.TemporaryDirectory() as directory:
   catalogue=OptionalCatalogue(SimpleNamespace(root=Path(directory),binary=Path(directory)/'llama.exe'))
   catalogue.entries={'a':{'repo':'author/model','revision':'r1'},'b':{'repo':'author/model','revision':'r1'}}
   with patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=lambda *a,**k:io.BytesIO(b'# Model card')) as fetch:
    a=catalogue.details('a');a['readme']='modified'
    self.assertEqual(catalogue.details('b')['readme'],'# Model card');self.assertEqual(fetch.call_count,1)
    catalogue.entries['b']['revision']='r2';catalogue.details('b');self.assertEqual(fetch.call_count,2)
    for i in range(70):
     catalogue.entries[str(i)]={'repo':'author/model'+str(i),'revision':'r1'};catalogue.details(str(i))
    self.assertEqual(len(catalogue.card_cache),64)
 def test_partial_base_card_retries_and_preserves_metadata(self):
  with tempfile.TemporaryDirectory() as directory:
   catalogue=OptionalCatalogue(SimpleNamespace(root=Path(directory),binary=Path(directory)/'llama.exe'))
   catalogue.entries={'a':{'repo':'author/model','revision':'r1','base_repo':'original/base','base_author':'original','license':'apache-2.0'}}
   with patch('serve.optional_catalogue.time.monotonic',return_value=0),patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'# Variant'),OSError('offline')]):
    result=catalogue.details('a');self.assertIsNone(result['base_readme'])
   with patch('serve.optional_catalogue.time.monotonic',return_value=61),patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'# Original')]) as fetch:
    self.assertEqual(catalogue.details('a')['base_readme'],'# Original');self.assertEqual(fetch.call_count,1)
   catalogue.card_cache.clear()
   with patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=OSError('offline')):
    result=catalogue.details('a');self.assertEqual(result['license'],'apache-2.0');self.assertEqual(result['author'],'author');self.assertEqual(result['base_author'],'original')
 def test_main_card_refreshes_without_invalidating_immutable_revision(self):
  with tempfile.TemporaryDirectory() as directory:
   catalogue=OptionalCatalogue(SimpleNamespace(root=Path(directory),binary=Path(directory)/'llama.exe'))
   catalogue.entries={'a':{'repo':'author/model','revision':'main'}}
   with patch('serve.optional_catalogue.time.monotonic',return_value=0),patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(b'# Old')):catalogue.details('a')
   with patch('serve.optional_catalogue.time.monotonic',return_value=901),patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(b'# New')) as fetch:
    self.assertEqual(catalogue.details('a')['readme'],'# New');self.assertEqual(fetch.call_count,1)
 def test_updated_metadata_reuses_document_without_stale_facts(self):
  with tempfile.TemporaryDirectory() as directory:
   catalogue=OptionalCatalogue(SimpleNamespace(root=Path(directory),binary=Path(directory)/'llama.exe'))
   catalogue.entries={'a':{'repo':'author/model','revision':'r1','license':'mit'}}
   with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(b'# Source')) as fetch:
    catalogue.details('a')
    catalogue.entries['a'].update(license='apache-2.0',author_metadata={'language':['it']},declared_bases=['a/base','b/base'])
    result=catalogue.details('a')
    self.assertEqual(result['license'],'apache-2.0');self.assertEqual(result['author_metadata'],{'language':['it']});self.assertEqual(fetch.call_count,1)
    result['author_metadata']['language'].append('bad')
    self.assertEqual(catalogue.details('a')['author_metadata']['language'],['it'])
 def test_mutable_base_refreshes_for_fixed_publication_revision(self):
  with tempfile.TemporaryDirectory() as directory:
   catalogue=OptionalCatalogue(SimpleNamespace(root=Path(directory),binary=Path(directory)/'llama.exe'))
   catalogue.entries={'a':{'repo':'author/model','revision':'fixed','base_repo':'original/base'}}
   with patch('serve.optional_catalogue.time.monotonic',return_value=0),patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'# Fixed'),io.BytesIO(b'# Old base')]):catalogue.details('a')
   with patch('serve.optional_catalogue.time.monotonic',return_value=901),patch('serve.optional_catalogue.urllib.request.urlopen',side_effect=[io.BytesIO(b'# Fixed'),io.BytesIO(b'# New base')]) as fetch:
    self.assertEqual(catalogue.details('a')['base_readme'],'# New base');self.assertEqual(fetch.call_count,2)
if __name__=='__main__':unittest.main()
