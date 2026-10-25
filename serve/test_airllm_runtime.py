import json,tempfile,unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from serve.airllm_runtime import validate_options, inspect_checkpoint, cache_directory, status

class AirLLMTests(unittest.TestCase):
    def test_options_reject_gpu_and_unsupported_features(self):
        validate_options('cpu',None,None,'none','auto','auto')
        for options in [('cuda',None,None,'none','auto','auto'),('cpu','adapter',None,'none','auto','auto'),('cpu',None,'draft','none','auto','auto'),('cpu',None,None,'nf4','auto','auto'),('cpu',None,None,'none','eager','auto')]:
            with self.assertRaises(ValueError):validate_options(*options)

    def test_pickle_index_is_rejected_even_when_safe_weights_exist(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            model=Path(directory)
            (model/'model.safetensors').write_bytes(b'fixture')
            (model/'pytorch_model.bin.index.json').write_text('{}')
            with self.assertRaises(ValueError):inspect_checkpoint(model)

    def test_shard_bound_and_cache_changes_with_weights(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root=Path(directory);model=root/'model';model.mkdir()
            (model/'config.json').write_text('{}')
            (model/'model.safetensors').write_bytes(b'fixture')
            info=inspect_checkpoint(model)
            first=cache_directory(root,model)
            self.assertGreaterEqual(info['conversion_ram_bytes'],7)
            (model/'model.safetensors').write_bytes(b'changed fixture')
            self.assertNotEqual(first,cache_directory(root,model))
            self.assertTrue(first.is_relative_to(root/'data/airllm-layer-cache'))

    def test_status_does_not_claim_inference_when_absent(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            row=status(Path(directory))
            self.assertFalse(row['installed']);self.assertFalse(row['inference_verified'])

    def test_upstream_remote_code_requests_are_forced_local_and_originals_preserved(self):
        from serve.airllm_runtime import load_cpu_model
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root=Path(directory);model=root/'model';model.mkdir()
            (model/'config.json').write_text('{}')
            (model/'model.safetensors').write_bytes(b'fixture')
            seen=[]
            class Factory:
                @classmethod
                def from_pretrained(cls,*args,**kwargs):
                    seen.append(kwargs);return SimpleNamespace()
            class ModelFactory:
                @classmethod
                def from_config(cls,*args,**kwargs):seen.append(kwargs);return SimpleNamespace()
            factories=SimpleNamespace(AutoConfig=Factory,AutoTokenizer=type('Tokenizer',(Factory,),{}),GenerationConfig=type('Generation',(Factory,),{}),AutoModelForCausalLM=ModelFactory)
            def constructor(*args,**kwargs):
                self.assertEqual(kwargs['device'],'cpu');self.assertFalse(kwargs['delete_original']);self.assertIsNone(kwargs['compression'])
                factories.AutoConfig.from_pretrained(str(model),trust_remote_code=True)
                factories.AutoTokenizer.from_pretrained(str(model),trust_remote_code=True)
                factories.AutoModelForCausalLM.from_config(SimpleNamespace(),trust_remote_code=True)
                return SimpleNamespace(model='owned model',tokenizer='owned tokenizer')
            with patch.dict('sys.modules',{'transformers':factories,'airllm':SimpleNamespace(AirLLMBaseModel=constructor)}):
                loaded=load_cpu_model(root,model,1024,SimpleNamespace(float32='f32'))
            self.assertEqual(loaded[:2],('owned model','owned tokenizer'))
            self.assertTrue(all(r['trust_remote_code'] is False for r in seen))
            self.assertTrue(all(r['local_files_only'] is True for r in seen[:2]))
            self.assertEqual((model/'model.safetensors').read_bytes(),b'fixture')

    def test_failed_new_release_install_does_not_change_active_environment(self):
        from serve.airllm_runtime import prepare,environment_directory
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root=Path(directory);base=environment_directory(root);base.mkdir(parents=True)
            selection=base/'selection.json';selection.write_text(json.dumps(dict(active_version='4.0.0')))
            old=selection.read_bytes()
            candidate=base/'environments/4.0.1/venv/Scripts';candidate.mkdir(parents=True)
            (candidate/'python.exe').write_bytes(b'fixture')
            from io import BytesIO
            with patch('serve.airllm_runtime.urllib.request.urlopen',return_value=BytesIO(json.dumps({'info':{'version':'4.0.1'},'releases':{'4.0.1':[]}}).encode())),patch('serve.airllm_runtime.subprocess.run',return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(ValueError):prepare(root)
            self.assertEqual(selection.read_bytes(),old)

    def test_selection_recheck_keeps_previous_and_rollback_checks_candidate(self):
        from serve.airllm_runtime import select_version,environment_directory
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            root=Path(directory);base=environment_directory(root);base.mkdir(parents=True)
            path=base/'selection.json';path.write_text(json.dumps({'active_version':'4.0.1','previous_version':'4.0.0'}))
            for version in ('4.0.0','4.0.1'):
                folder=base/'environments'/version;folder.mkdir(parents=True)
                (folder/'environment-manifest.json').write_text(json.dumps({'dependency_health':{'state':'healthy'},'imports_verified':True,'environment_sha256':'known'}))
            with patch('serve.airllm_runtime._inventory',return_value='known'),patch('serve.airllm_runtime._probe_python'),patch('serve.airllm_runtime.status',return_value={}):
                original=path.read_bytes();select_version(root,'4.0.1');self.assertEqual(path.read_bytes(),original)
                select_version(root,None,rollback=True)
                result=json.loads(path.read_text());self.assertEqual(result['active_version'],'4.0.0');self.assertEqual(result['previous_version'],'4.0.1')
            original=path.read_bytes()
            with patch('serve.airllm_runtime._inventory',return_value='changed'):
                with self.assertRaises(ValueError):select_version(root,None,rollback=True)
            self.assertEqual(path.read_bytes(),original)

if __name__=='__main__':unittest.main()
