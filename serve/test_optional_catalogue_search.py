"""Discovery and pagination contracts; fixtures do not certify remote model loading."""
import tempfile,unittest,urllib.parse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.optional_catalogue import OptionalCatalogue

class SearchTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);binary=root/'server.exe';binary.touch()
        self.catalogue=OptionalCatalogue(SimpleNamespace(root=root,binary=binary,models_root=root/'models'))
        self.host=patch('serve.optional_catalogue.host',return_value=dict(ram_total_gib=64,vram_total_gib=24,free_gib=100));self.host.start();self.addCleanup(self.host.stop)
    def info(self,url):
        repo=url.split('/api/models/')[1]
        return dict(id=repo,sha='a'*40,pipeline_tag='text-generation',cardData={})
    def page(self,url):
        if '/tree/' in url:
            return [dict(type='file',path=f'model-Q{i}_K.gguf',size=2**30,lfs=dict(oid='b'*64)) for i in range(2,7)],None
        page=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if 'cursor' in page:return [{'id':'community/second'}],None
        return [{'id':'community/first'}],'https://huggingface.co/api/models?cursor=second'
    def run_search(self,payload):
        with patch('serve.optional_catalogue.get_json',side_effect=self.info),patch('serve.optional_catalogue.get_json_page',side_effect=self.page),patch.object(self.catalogue,'_header',return_value={'general.architecture':'qwen3','tokenizer.chat_template':True}),patch('serve.optional_catalogue.base_identity',return_value={}):
            return self.catalogue.search(payload)
    def test_next_page_is_accessible_and_keeps_filters(self):
        payload=dict(category='all',author='community',query='model')
        first=self.run_search(payload);self.assertTrue(first['has_more'])
        second=self.run_search({**payload,'cursor':first['next_cursor']})
        self.assertEqual(second['results'][0]['repo'],'community/second');self.assertFalse(second['has_more'])
        with self.assertRaises(ValueError):self.run_search({**payload,'query':'other','cursor':first['next_cursor']})
    def test_exact_repository_exposes_every_compatible_quantization(self):
        result=self.run_search(dict(category='all',author='community',query='community/exact'))
        self.assertEqual(len(result['results']),5);self.assertFalse(result['variants_limited'])
    def test_low_disk_space_does_not_hide_compatible_models(self):
        with patch('serve.optional_catalogue.host',return_value=dict(ram_total_gib=64,vram_total_gib=24,free_gib=.5)):
            result=self.run_search(dict(category='all',query='community/exact'))
        self.assertEqual(len(result['results']),5)
        self.assertTrue(all(row['download_space_available'] is False for row in result['results']))

    def test_download_checks_destination_volume_before_starting(self):
        destination=self.catalogue.manager.root/'separate-volume';destination.mkdir()
        self.catalogue.manager.models_root=destination/'models'
        self.catalogue.entries['test']={'path':str(destination/'models'/'nested'/'model.gguf'),'bytes':2**30,'name':'test'}
        with patch('serve.optional_catalogue.shutil.disk_usage',return_value=SimpleNamespace(free=0)) as disk:
            with self.assertRaisesRegex(ValueError,'destinazione'):self.catalogue.download('test')
            disk.assert_called_once_with(destination)
        self.assertNotEqual(self.catalogue.job['state'],'downloading')

    def test_cached_search_refreshes_disk_capacity_without_network(self):
        payload=dict(category='all',query='community/exact')
        self.run_search(payload)
        with patch('serve.optional_catalogue.host',return_value=dict(ram_total_gib=64,vram_total_gib=24,free_gib=.5)),patch('serve.optional_catalogue.get_json_page',side_effect=AssertionError('No extra network')):
            result=self.catalogue.search(payload)
        self.assertEqual(result['host']['free_gib'],.5)
        self.assertTrue(all(not r['download_space_available'] for r in result['results']))

    def test_discovery_network_error_is_not_an_empty_catalogue(self):
        with patch('serve.optional_catalogue.get_json_page',side_effect=OSError('offline')):
            with self.assertRaisesRegex(RuntimeError,'Hugging Face'):self.catalogue.search(dict(category='all'))
    def test_author_name_search_uses_author_filter(self):
        with patch('serve.optional_catalogue.get_json_page',return_value=([],None)) as page:
            self.catalogue.search(dict(category='all',query='unsloth'))
            params=urllib.parse.parse_qs(urllib.parse.urlsplit(page.call_args.args[0]).query)
            self.assertEqual(params['author'],['unsloth'])
    def test_file_tree_pagination_is_followed(self):
        count=[]
        def page(url):
            if '/tree/' not in url:return [],None
            count.append(url)
            if '?cursor=' not in url:return [],url.split('?')[0]+'?cursor=files'
            return self.page(url)
        with patch('serve.optional_catalogue.get_json',side_effect=self.info),patch('serve.optional_catalogue.get_json_page',side_effect=page),patch.object(self.catalogue,'_header',return_value={'general.architecture':'qwen3','tokenizer.chat_template':True}),patch('serve.optional_catalogue.base_identity',return_value={}):
            result=self.catalogue.search(dict(category='all',query='community/exact'))
        self.assertEqual(len(count),2);self.assertEqual(len(result['results']),5)

    def test_hub_metadata_discovers_all_variants_without_reading_weights(self):
        def info(url):
            return {**self.info(url),'gguf':dict(architecture='qwen3',chat_template='template',total=600000000,context_length=40960)}
        with patch('serve.optional_catalogue.get_json',side_effect=info),patch('serve.optional_catalogue.get_json_page',side_effect=self.page),patch.object(self.catalogue,'_header') as header,patch('serve.optional_catalogue.base_identity',return_value={}):
            result=self.catalogue.search(dict(category='all',author='community'))
        header.assert_not_called();self.assertEqual(len(result['results']),5)
        self.assertTrue(all(row['verification']=='hub_metadata_and_capacity' for row in result['results']))

    def test_download_checks_hub_metadata_against_the_actual_file(self):
        import hashlib,io
        content=b'GGUFtest';target=self.catalogue.manager.models_root/'model.gguf'
        entry=dict(path=str(target),url='https://huggingface.co/file',bytes=len(content),sha256=hashlib.sha256(content).hexdigest(),architecture='qwen3',verification='hub_metadata_and_capacity')
        with patch('serve.optional_catalogue.urllib.request.urlopen',return_value=io.BytesIO(content)),patch('serve.optional_catalogue.read_gguf_header',return_value={'meta':{'general.architecture':'unsupported','tokenizer.chat_template':'template'}}):
            self.catalogue._download(entry)
        self.assertEqual(self.catalogue.job['state'],'failed');self.assertFalse(target.exists());self.assertFalse(target.with_suffix('.gguf.download').exists())

    def test_large_hybrid_variant_uses_host_capacity_instead_of_fixed_48_gib(self):
        def page(url):
            if '/tree/' in url:return [dict(type='file',path='model-Q4_K_M.gguf',size=52*2**30,lfs=dict(oid='b'*64))],None
            return [{'id':'community/large'}],None
        with patch('serve.optional_catalogue.get_json',side_effect=self.info),patch('serve.optional_catalogue.get_json_page',side_effect=page),patch.object(self.catalogue,'_header',return_value={'general.architecture':'qwen3','tokenizer.chat_template':True}),patch('serve.optional_catalogue.base_identity',return_value={}):
            result=self.catalogue.search(dict(category='all',query='community/large'))
        self.assertEqual(len(result['results']),1);self.assertEqual(result['results'][0]['execution_mode'],'hybrid')
        self.catalogue.search_cache.clear()
        with patch('serve.optional_catalogue.host',return_value=dict(ram_total_gib=32,vram_total_gib=12,free_gib=100)),patch('serve.optional_catalogue.get_json',side_effect=self.info),patch('serve.optional_catalogue.get_json_page',side_effect=page),patch.object(self.catalogue,'_header',return_value={'general.architecture':'qwen3','tokenizer.chat_template':True}),patch('serve.optional_catalogue.base_identity',return_value={}):
            self.assertFalse(self.catalogue.search(dict(category='all',query='community/large'))['results'])

    def test_split_variant_is_one_model_with_total_size_and_all_hashes(self):
        def page(url):
            return [dict(type='file',path=f'Q4_K_M/model-Q4_K_M-{number:05d}-of-00002.gguf',size=2**30,lfs={'oid':'b'*64}) for number in (1,2)],None
        with patch('serve.optional_catalogue.get_json',side_effect=self.info),patch('serve.optional_catalogue.get_json_page',side_effect=page),patch.object(self.catalogue,'_header',return_value={'general.architecture':'qwen3','tokenizer.chat_template':True}),patch('serve.optional_catalogue.base_identity',return_value={}):
            result=self.catalogue.search(dict(category='all',query='community/exact'))
        self.assertEqual(len(result['results']),1);entry=result['results'][0]
        self.assertEqual(entry['bytes'],2*2**30);self.assertEqual(entry['parts'],2);self.assertEqual(entry['quantization'],'Q4_K_M')
        self.assertTrue(all('Q4_K_M' in Path(part['path']).parts for part in entry['shards']))

if __name__=='__main__':unittest.main()
