import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from serve.optional_benchmark import OptionalBenchmark
from serve.optional_catalogue import OptionalCatalogue
from serve.optional_reports import reports,best_groups

class WorkflowTests(unittest.TestCase):
 def test_api_without_engine_timings_keeps_wall_measurements_separate(self):
  def chat(payload,cancel):
   self.assertNotIn('chat_template_kwargs',payload)
   self.assertNotIn('cache_prompt',payload)
   yield dict(usage={'completion_tokens':payload['max_tokens']},choices=[{'message':{'content':'response'}}])
  self.manager.chat=chat;b=OptionalBenchmark(self.manager)
  b.start({'runs':3,'tokens':32})
  deadline=time.monotonic()+3
  while self.manager.conversation_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
  job=b.status()[0]
  self.assertEqual(job['status'],'complete')
  summary=job['results'][0]['summary']
  self.assertGreater(summary['wall_tok_s']['median'],0)
  self.assertNotIn('decode_tok_s',summary)
  self.assertNotIn('prefill_tok_s',summary)
  imported=reports(self.root)
  self.assertEqual(len(imported),1)
  self.assertNotIn('decode_tok_s',imported[0]['summary'])
  self.assertEqual(best_groups(imported,'local/test'),[]) # Never promote wall rate as a decode record.

 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.manager=SimpleNamespace(root=self.root,conversation_lock=threading.Lock(),binary=self.root/'llama.exe',models_root=self.root/'models',model_cache_at=0,
   status=lambda:dict(status='ready',public_model='local/test',model='test',profile='balanced'))
 def test_benchmark_persists_and_recomputes_report(self):
  def chat(payload,cancel):
   yield dict(usage={'completion_tokens':payload['max_tokens']},timings={'predicted_per_second':12,'prompt_per_second':30},choices=[{'message':{'content':'12'}}])
  self.manager.chat=chat;b=OptionalBenchmark(self.manager)
  b.start({'runs':3,'tokens':32,'quality':True})
  deadline=time.monotonic()+3
  while self.manager.conversation_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
  self.assertFalse(self.manager.conversation_lock.locked());job=b.status()[0]
  self.assertEqual(job['status'],'complete');self.assertEqual(job['results'][0]['quality']['correct'],0);self.assertEqual(job['results'][0]['quality']['total'],12);self.assertEqual(job['completed_samples'],16);self.assertEqual(job['total_samples'],16)
  rows=reports(self.root);self.assertEqual(rows[0]['summary']['decode_tok_s']['median'],12)
  self.assertEqual(best_groups(rows,'local/test')[0]['winner']['summary']['decode_tok_s'],12)
  self.assertEqual(best_groups(rows,'other'),[])
 def test_benchmark_records_short_output_without_inventing_tokens(self):
  self.manager.chat=lambda *args:iter([{'usage':{'completion_tokens':2},'choices':[{'message':{'content':'short'}}]}]);b=OptionalBenchmark(self.manager)
  b.start({'runs':3,'tokens':32});deadline=time.monotonic()+3
  while self.manager.conversation_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
  self.assertEqual(b.status()[0]['status'],'complete');rows=reports(self.root);self.assertEqual(len(rows),1);self.assertFalse(rows[0]['protocol']['full_budget']);self.assertEqual(best_groups(rows,'local/test'),[])
 def test_backend_without_usage_records_latency_only(self):
  self.manager.chat=lambda *args:iter([{'choices':[{'message':{'content':'completed'}}]}])
  benchmark=OptionalBenchmark(self.manager);benchmark.start({'runs':3,'tokens':32});deadline=time.monotonic()+3
  while self.manager.conversation_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
  job=benchmark.status()[0];self.assertEqual(job['status'],'complete');summary=job['results'][0]['summary'];self.assertIn('wall_s',summary);self.assertNotIn('wall_tok_s',summary);self.assertIsNone(job['sample_series'][0]['output_tokens'])
  imported=reports(self.root);self.assertEqual(len(imported),1);self.assertNotIn('wall_tok_s',imported[0]['summary'])
 def test_invalid_token_count_fails_without_promotion(self):
  self.manager.chat=lambda *args:iter([{'usage':{'completion_tokens':True},'choices':[{'message':{'content':'completed'}}]}])
  benchmark=OptionalBenchmark(self.manager);benchmark.start({'runs':3,'tokens':32});deadline=time.monotonic()+3
  while self.manager.conversation_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
  self.assertEqual(benchmark.status()[0]['status'],'failed');self.assertEqual(reports(self.root),[])
 def test_conversation_reservation(self):
  self.manager.conversation_lock.acquire();b=OptionalBenchmark(self.manager)
  with self.assertRaises(RuntimeError):b.start({'runs':3,'tokens':32})
 def test_download_verifies_hash_and_registers_path(self):
  import hashlib,io
  c=OptionalCatalogue(self.manager);content=b'GGUF'+b'verified weights fixture';target=self.root/'models/test.gguf'
  entry=dict(path=str(target),url='https://huggingface.co/fixture',bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
  with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(content)):
   c._download(entry)
  self.assertEqual(c.status()['state'],'complete');self.assertEqual(target.read_bytes(),content)
  bad=self.root/'models/bad.gguf';entry={**entry,'path':str(bad),'sha256':'a'*64}
  with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(content)):
   c._download(entry)
  self.assertEqual(c.status()['state'],'failed');self.assertFalse(bad.exists());self.assertFalse(bad.with_suffix('.gguf.download').exists())
 def test_catalogue_rejects_unverified_download(self):
  c=OptionalCatalogue(self.manager)
  with self.assertRaises(ValueError):c.download('../arbitrary')
 def test_author_filter_uses_live_discovery_in_every_category(self):
  from serve.optional_catalogue import CATEGORIES
  self.manager.binary.write_bytes(b'x');c=OptionalCatalogue(self.manager)
  with patch('serve.optional_catalogue.host',return_value=dict(ram_total_gib=64,vram_total_gib=24)),patch('serve.optional_catalogue.get_json',return_value=[]),patch('serve.optional_catalogue.get_json_page',return_value=([],None)):
   self.assertEqual(c.search(dict(category='code',author='unsloth'))['search_terms'],[''])
   self.assertEqual(c.search(dict(category='all',author='unsloth'))['search_terms'],[''])
 def test_catalogue_checks_capacity_architecture_and_hash(self):
  self.manager.binary.write_bytes(b'x');c=OptionalCatalogue(self.manager)
  def api(url):
   if '/api/models?' in url:return [{'id':'author/model'}]
   if '/tree/' in url:return [{'type':'file','path':'model-Q4_K_M.gguf','size':2**30,'lfs':{'oid':'b'*64}}]
   return {'sha':'a'*40,'pipeline_tag':'text-generation','cardData':{'license':'apache-2.0'}}
  resources=dict(ram_total_gib=64,vram_total_gib=24,free_gib=100)
  with patch('serve.optional_catalogue.host',return_value=resources),patch('serve.optional_catalogue.get_json',side_effect=api),patch('serve.optional_catalogue.get_json_page',side_effect=lambda url:(api(url),None)),patch('serve.optional_catalogue.read_gguf_header',return_value={'meta':{'general.architecture':'qwen3','tokenizer.chat_template':'template'}}):
   rows=c.search({'category':'chat'})['results'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['revision'],'a'*40)
  with patch('serve.optional_catalogue.host',return_value={**resources,'vram_total_gib':4}),patch('serve.optional_catalogue.get_json',side_effect=api),patch('serve.optional_catalogue.get_json_page',side_effect=lambda url:(api(url),None)),patch('serve.optional_catalogue.read_gguf_header',return_value={'meta':{'general.architecture':'qwen3','tokenizer.chat_template':'template'}}):
   self.assertEqual(c.search({'category':'chat'})['results'][0]['execution_mode'],'hybrid')

class HeaderCacheTests(unittest.TestCase):
 def test_revision_header_is_reused_and_persisted_without_tokens(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);manager=SimpleNamespace(root=root,binary=root/'server.exe')
   catalogue=OptionalCatalogue(manager)
   metadata={'general.architecture':'qwen3','tokenizer.chat_template':'actual template','tokenizer.ggml.tokens':['large vocabulary'],'qwen3.context_length':32768}
   url='https://huggingface.co/publisher/model/resolve/'+'a'*40+'/model.gguf'
   with patch('serve.optional_catalogue.read_gguf_header',return_value={'meta':metadata}) as read:
    catalogue._header(url);catalogue._header(url);self.assertEqual(read.call_count,1)
   catalogue._save_headers();self.assertLess(catalogue.header_cache_path.stat().st_size,2048)
   restored=OptionalCatalogue(manager)
   with patch('serve.optional_catalogue.read_gguf_header') as read:
    self.assertEqual(restored._header(url)['qwen3.context_length'],32768);read.assert_not_called()
   self.assertNotIn('tokenizer.ggml.tokens',restored._header(url))

class DownloadCleanupTests(unittest.TestCase):
 def test_cancelled_transfer_removes_partial_without_registering_model(self):
  import io,hashlib
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);manager=SimpleNamespace(root=root,binary=root/'server.exe')
   catalogue=OptionalCatalogue(manager);target=root/'models/cancel.gguf';content=b'GGUFtest'
   entry=dict(path=str(target),url='https://huggingface.co/fixture',bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
   catalogue.cancel.set()
   with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(content)):catalogue._download(entry)
   self.assertEqual(catalogue.status()['state'],'cancelled');self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.gguf.download').exists())
 def test_oversized_response_removes_partial(self):
  import io
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);catalogue=OptionalCatalogue(SimpleNamespace(root=root,binary=root/'server.exe'));target=root/'models/oversized.gguf'
   with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(b'GGUFtoo large')):
    catalogue._download(dict(path=str(target),url='https://huggingface.co/fixture',bytes=4,sha256='a'*64))
   self.assertEqual(catalogue.status()['state'],'failed');self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.gguf.download').exists())

if __name__=='__main__':unittest.main()
