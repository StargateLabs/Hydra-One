"""Control-plane fixtures: never launch a backend or load native dependencies."""
import json,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch

def gguf(path,architecture='llama',template='{{ messages }}'):
    def string(value):
        data=value.encode();return struct.pack('<Q',len(data))+data
    fields={'general.architecture':architecture,'tokenizer.chat_template':template}
    path.write_bytes(b'GGUF'+struct.pack('<IQQ',3,0,len(fields))+b''.join(string(k)+struct.pack('<I',8)+string(v) for k,v in fields.items()))

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.path=self.root/'model.gguf';gguf(self.path)
        self.payload={'model_path':str(self.path),'engine_addon':'hydra-one','mode':'auto','gpu':False,'context':1024,'runtime':{}}
    def resolve(self,**changes):
        from serve.hydra_control import resolve_model
        return resolve_model(self.root,{**self.payload,**changes},architectures={'llama','qwen3'})
    def test_real_fixture_header_resolves_and_no_launch(self):
        row=self.resolve();self.assertEqual(row['route'],'hydra-gguf');self.assertEqual(row['mode'],'gguf');self.assertEqual(row['architecture'],'llama');self.assertTrue(row['available']);self.assertFalse(row['reserved'])
    def test_unknown_architecture_fails_closed(self):
        gguf(self.path,'alien');self.assertFalse(self.resolve()['available'])
    def test_missing_chat_template_fails_closed(self):
        gguf(self.path,template='');self.assertFalse(self.resolve()['available'])
    def test_missing_file_fails_closed(self):
        self.assertFalse(self.resolve(model_path=str(self.root/'missing.gguf'))['available'])
    def test_wrong_mode_is_rejected(self):
        self.assertFalse(self.resolve(mode='safetensors')['available'])
    def test_wrong_magic_is_rejected(self):
        self.path.write_bytes(b'not gguf');self.assertFalse(self.resolve()['available'])
    def test_unknown_format_fails_closed(self):
        p=self.root/'weights.bin';p.write_bytes(b'anything');self.assertFalse(self.resolve(model_path=str(p))['available'])
    def test_embedding_not_admitted_as_chat(self):
        gguf(self.path,'nomic-bert');self.assertFalse(self.resolve()['available'])
    def test_pack_takes_precedence_over_extension(self):
        with patch('serve.model_engine_requirements.requirement',return_value={'required_engine':'strata','strata_ready':True,'strata_key':'fixture','strata_configuration':'strata-fixture.json'}):
            row=self.resolve();self.assertEqual(row['route'],'hydra-strata');self.assertEqual(row['profile'],'fixture')
    def test_incomplete_pack_rejected(self):
        with patch('serve.model_engine_requirements.requirement',return_value={'required_engine':'strata','strata_ready':False}):self.assertFalse(self.resolve()['available'])
    def test_safe_model_requires_local_tokenizer(self):
        folder=self.root/'safe';folder.mkdir();(folder/'model.safetensors').write_bytes(b'fixture')
        (folder/'config.json').write_text(json.dumps({'architectures':['LlamaForCausalLM'],'model_type':'llama','max_position_embeddings':2048,'num_hidden_layers':1,'num_attention_heads':1,'hidden_size':8}))
        self.assertFalse(self.resolve(model_path=str(folder))['available'])
        (folder/'tokenizer.json').write_text('{}');self.assertEqual(self.resolve(model_path=str(folder))['route'],'hydra-safetensors')
    def test_lora_without_matching_base_rejected(self):
        folder=self.root/'lora';folder.mkdir();(folder/'adapter_config.json').write_text('{}');self.assertFalse(self.resolve(model_path=str(folder))['available'])
    def test_plan_uses_existing_memory_owner(self):
        from serve.hydra_control import model_plan
        manager=Mock(root=self.root);manager.fit_model.return_value={'recommended':{'gpu':False,'context':1024,'runtime':{'threads':2}},'scope':'fixture memory estimate'}
        with patch('serve.hydra_control.resolve_model',return_value=self.resolve()):row=model_plan(manager,self.payload)
        manager.fit_model.assert_called_once();self.assertFalse(row['reserved']);self.assertEqual(row['resource_owner'],'existing_backend_manager');self.assertEqual(row['performance'],'NOT_MEASURED')
    def test_denied_model_never_calls_planner(self):
        from serve.hydra_control import model_plan
        manager=Mock(root=self.root)
        with patch('serve.hydra_control.resolve_model',return_value={'available':False,'reason':'unknown','reserved':False}):row=model_plan(manager,self.payload)
        manager.fit_model.assert_not_called();self.assertFalse(row['available'])
    def test_start_guard_rejects_wrong_destination(self):
        from serve.hydra_control import normalize_start
        with self.assertRaises(ValueError):normalize_start(self.root,{**self.payload,'mode':'safetensors'},architectures={'llama'})
    def test_start_normalizes_without_mutating_caller(self):
        from serve.hydra_control import normalize_start
        out=normalize_start(self.root,self.payload,architectures={'llama'});self.assertEqual(out['mode'],'gguf');self.assertEqual(self.payload['mode'],'auto')
    def test_bad_runtime_fails_closed(self):
        self.assertFalse(self.resolve(runtime=[])['available'])
    def test_profile_traversal_rejected(self):
        self.assertFalse(self.resolve(model_path=None,profile='../escape')['available'])
    def test_replaced_model_rechecked_at_start(self):
        from serve.hydra_control import normalize_start
        self.assertTrue(self.resolve()['available']);gguf(self.path,'alien')
        with self.assertRaises(ValueError):normalize_start(self.root,self.payload,architectures={'llama'})
    def test_resource_failure_does_not_admit(self):
        from serve.hydra_control import model_plan
        manager=Mock(root=self.root);manager.fit_model.side_effect=ValueError('insufficient memory')
        with patch('serve.hydra_control.resolve_model',return_value=self.resolve()):row=model_plan(manager,self.payload)
        self.assertFalse(row['available']);self.assertFalse(row['reserved'])
    def test_http_inspection_does_not_plan_or_launch(self):
        from serve.hydra_control import route
        handler=Mock();handler._read_body.return_value=json.dumps({**self.payload,'inspect_only':True}).encode();service=Mock();service.optional_backends.root=self.root
        with patch('serve.hydra_control.resolve_model',return_value=self.resolve()):self.assertTrue(route(handler,service,'/hydra/model-plan'))
        service.optional_backends.fit_model.assert_not_called();service.optional_backends.start.assert_not_called();handler._json.assert_called_once()
    def test_same_origin_denial_stops_handler(self):
        from serve.hydra_control import route
        handler=Mock();handler._own_page.return_value=False
        self.assertTrue(route(handler,Mock(),'/hydra/model-plan'));handler._read_body.assert_not_called()

if __name__=='__main__':unittest.main()
