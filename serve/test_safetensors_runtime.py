import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from serve.safetensors_runtime import inspect_model,normalize_messages,parsed_message,requested_tools,attention_options,cache_options

class NativeRuntimeTests(unittest.TestCase):
    def test_generic_declared_tokenizer_preserves_serialized_backend(self):
        from serve.safetensors_runtime import load_local_tokenizer
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'tokenizer_config.json').write_text(json.dumps(dict(tokenizer_class='TokenizersBackend')))
            calls=[]
            class Generic:
                @classmethod
                def from_pretrained(cls,*args,**kwargs):calls.append(kwargs);return 'serialized WordLevel'
            def guessed(*args,**kwargs):raise AssertionError('Must not guess Qwen tokenizer from model type')
            with patch.dict('sys.modules',{'transformers':SimpleNamespace(TokenizersBackend=Generic)}):
                self.assertEqual(load_local_tokenizer(folder,guessed),'serialized WordLevel')
            self.assertEqual(calls,[dict(local_files_only=True,trust_remote_code=False)])

    def test_cache_options_preserve_auto_and_reject_native_overrides(self):
        self.assertEqual(cache_options('transformers','auto'),{})
        self.assertEqual(cache_options('transformers','dynamic'),{'use_cache':True,'cache_implementation':'dynamic'})
        self.assertEqual(cache_options('transformers','off'),{'use_cache':False})
        with self.assertRaises(ValueError):cache_options('unsloth','dynamic')

    def test_attention_selection_is_explicit_and_loader_specific(self):
        self.assertEqual(attention_options('transformers','auto'),{})
        self.assertEqual(attention_options('transformers','sdpa'),{'attn_implementation':'sdpa'})
        self.assertEqual(attention_options('transformers','eager'),{'attn_implementation':'eager'})
        for loader,attention in [('unsloth','sdpa'),('transformers','flash_attention_2')]:
            with self.assertRaises(ValueError):attention_options(loader,attention)

    def test_explicit_head_dimension_controls_cache_estimate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config=dict(architectures=['GemmaForCausalLM'],max_position_embeddings=262144,
                hidden_size=64,num_hidden_layers=2,num_attention_heads=4,num_key_value_heads=2,head_dim=32)
            (root/'model.safetensors').write_bytes(b'fixture')
            (root/'config.json').write_text(json.dumps(config))
            self.assertEqual(inspect_model(root)['kv_bytes_per_token'],1024)
            config['head_dim']=False
            (root/'config.json').write_text(json.dumps(config))
            self.assertIsNone(inspect_model(root)['kv_bytes_per_token'])

    def test_index_must_include_every_local_shard(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'config.json').write_text(json.dumps(dict(architectures=['Qwen2ForCausalLM'],max_position_embeddings=32768,
                hidden_size=64,num_hidden_layers=2,num_attention_heads=4,num_key_value_heads=2)))
            (root/'model.safetensors').write_bytes(b'fixture')
            info=inspect_model(root)
            self.assertEqual(info['kv_bytes_per_token'],512)
            (root/'model.safetensors.index.json').write_text(json.dumps(dict(weight_map={'missing':'missing.safetensors'})))
            with self.assertRaises(ValueError):inspect_model(root)

    def test_embeddings_not_advertised_as_chat_models(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'config.json').write_text(json.dumps(dict(architectures=['BertModel'])))
            with self.assertRaises(ValueError):inspect_model(root)

    def test_template_receives_object_arguments_and_original_history_unchanged(self):
        source=[dict(role='assistant',content=None,tool_calls=[dict(function=dict(name='search',arguments='"{\\"query\\":\\"test\\"}"'))])]
        result=normalize_messages(source)
        self.assertEqual(result[0]['tool_calls'][0]['function']['arguments'],{'query':'test'})
        self.assertIsInstance(source[0]['tool_calls'][0]['function']['arguments'],str)

    def test_tool_parser_returns_openai_argument_string_and_identity(self):
        tokenizer=SimpleNamespace(response_schema=True,parse_response=lambda text:dict(content=None,tool_calls=[dict(function=dict(name='search',arguments={'query':'test'}))]))
        message=parsed_message(tokenizer,'fixture')
        call=message['tool_calls'][0]
        self.assertEqual(json.loads(call['function']['arguments']),{'query':'test'})
        self.assertTrue(call['id']);self.assertEqual(call['type'],'function')

    def test_multimodal_payload_rejected_explicitly(self):
        with self.assertRaises(ValueError):normalize_messages([dict(role='user',content=[dict(type='image_url')])])

    def test_schema_parser_normalizes_json_without_mutating_parser_result(self):
        source=dict(content=None,tool_calls=[dict(function=dict(name='search',arguments='{"query":"weather"}'))])
        tokenizer=SimpleNamespace(response_schema=True,parse_response=lambda text:source)
        result=parsed_message(tokenizer,'fixture',{'search'})
        self.assertEqual(json.loads(result['tool_calls'][0]['function']['arguments']),{'query':'weather'})
        self.assertNotIn('id',source['tool_calls'][0])

    def test_schema_parser_rejects_invalid_calls_before_dispatch(self):
        cases=[dict(tool_calls={}),dict(tool_calls=[None]),dict(tool_calls=[dict(function={})]),
            dict(content=[]),dict(tool_calls=[dict(function=dict(name='search',arguments='[]'))]),
            dict(tool_calls=[dict(function=dict(name='search',arguments={'value':float('nan')}))]),
            dict(tool_calls=[dict(id='same',function=dict(name='search')),dict(id='same',function=dict(name='search'))])]
        for response in cases:
            with self.subTest(response=response):
                tokenizer=SimpleNamespace(response_schema=True,parse_response=lambda text:response)
                with self.assertRaises(ValueError):parsed_message(tokenizer,'fixture',{'search'})

class ToolContractTests(unittest.TestCase):
    def test_none_does_not_expose_tools_to_template(self):
        self.assertIsNone(requested_tools({'tools':[{'type':'function','function':{'name':'search_web'}}],'tool_choice':'none'}))
    def test_unsupported_forced_tools_are_explicit(self):
        for choice in ('required',{'type':'function','function':{'name':'search_web'}}):
            with self.assertRaises(ValueError):requested_tools({'tool_choice':choice})
    def test_duplicate_tools_rejected(self):
        tool={'type':'function','function':{'name':'search_web'}}
        with self.assertRaises(ValueError):requested_tools({'tools':[tool,tool]})

class QwenProtocolTests(unittest.TestCase):
    def tokenizer(self):return SimpleNamespace(chat_template='<tool_call></tool_call> arguments tools')
    def test_reasoning_and_tool_are_separated(self):
        result=parsed_message(self.tokenizer(),'<think>check weather</think><tool_call>{"name":"search","arguments":{"query":"weather"}}</tool_call>',{'search'})
        self.assertEqual(result['reasoning_content'],'check weather')
        self.assertIsNone(result['content'])
        self.assertEqual(json.loads(result['tool_calls'][0]['function']['arguments']),{'query':'weather'})
    def test_unknown_and_incomplete_calls_rejected(self):
        for text in ['<tool_call>{"name":"hidden","arguments":{}}</tool_call>','<tool_call>{',
                     '<tool_call>{"name":"search","arguments":{}}</tool_call><tool_call>{',
                     'text</tool_call>']:
            with self.assertRaises(ValueError):parsed_message(self.tokenizer(),text,{'search'})
