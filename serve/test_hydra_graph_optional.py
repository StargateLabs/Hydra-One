import unittest
from types import SimpleNamespace
from unittest.mock import patch


class OptionalGraphTests(unittest.TestCase):
    def test_simple_request_does_not_read_model_metadata_or_call_runtime(self):
        from serve.hydra_graph_optional import OptionalGraph
        config=dict(graph_enabled=True,context_compiler_enabled=True,adaptive_controller_enabled=True,
                    shared_corpus_authorized=True,scope='project',allowed_sources=['unused-source'])
        bridge=OptionalGraph(SimpleNamespace(graph_config=lambda:config),None,{'mode':'gguf','model_path':'unused-model.gguf'})
        messages=[{'role':'user','content':'Reply OK.'}]
        with patch('tools.gguf_reader.GGUFFile') as metadata,patch.object(bridge,'post') as post:
            self.assertIs(bridge.prepare(messages,{},8),messages)
            metadata.assert_not_called();post.assert_not_called()
        self.assertEqual(bridge.snapshot()['last']['reason'],'retrieval_cost_not_justified')

    def test_model_inventory_is_loaded_only_when_needed_and_reused(self):
        from serve.hydra_graph_optional import OptionalGraph
        bridge=OptionalGraph(SimpleNamespace(),None,{'mode':'gguf','model_path':'model.gguf'})
        with patch('tools.gguf_reader.GGUFFile',return_value=SimpleNamespace(metadata={
                'tokenizer.ggml.tokens':['ordinary','<special>'],'tokenizer.ggml.token_type':[1,3]})) as metadata:
            bridge.initialize()
            metadata.assert_not_called()
            bridge.deadline=__import__('time').monotonic()+1
            self.assertEqual(bridge.service.tok.special_tokens,{'<special>':1})
            self.assertEqual(bridge.service.tok.special_tokens,{'<special>':1})
            self.assertEqual(metadata.call_count,1)

    def test_deferred_inventory_failure_preserves_original_context(self):
        import tempfile
        from pathlib import Path
        from serve.hydra_graph_memory import GraphMemory
        from serve.hydra_graph_optional import OptionalGraph
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.txt'
            source.write_text('Native cache is owned by the original runtime.',encoding='utf-8')
            database=root/'graph.sqlite'
            GraphMemory.create(database,roots=[root]).ingest('project',source)
            config=dict(graph_enabled=True,context_compiler_enabled=True,shared_corpus_authorized=True,
                        scope='project',database=str(database),source_roots=[str(root)],allowed_sources=[str(source)])
            bridge=OptionalGraph(SimpleNamespace(graph_config=lambda:config),None,
                                 {'mode':'gguf','model_path':str(root/'private-model.gguf')})
            messages=[{'role':'system','content':'Preserve this instruction.'},{'role':'user','content':'Explain the native cache.'}]
            self.assertIs(bridge.prepare(messages,{},8),messages)
            status=bridge.snapshot()
            self.assertTrue(status['last']['fallback'])
            self.assertEqual(status['last']['error_type'],'FileNotFoundError')
            self.assertNotIn('private-model',repr(status))

    def test_fitted_context_is_bounded_by_observed_slot_context(self):
        from serve.hydra_graph_optional import OptionalGraph
        owner=SimpleNamespace(state={'context':4096})
        bridge=OptionalGraph(owner,None,{'context':8192,'runtime':{'slots':2}})
        self.assertEqual(bridge.context_limit(),2048)
        owner.state['context']=16384
        self.assertEqual(bridge.context_limit(),4096)

    def test_cancelled_request_never_opens_runtime(self):
        import threading
        from serve.hydra_graph_optional import OptionalGraph
        cancel=threading.Event();cancel.set()
        bridge=OptionalGraph(SimpleNamespace(graph_config=lambda:dict(graph_enabled=True,context_compiler_enabled=True)),None,{'mode':'gguf'})
        messages=[{'role':'user','content':'hello'}]
        with patch.object(bridge,'initialize',side_effect=AssertionError('cancelled')):
            self.assertIs(bridge.prepare(messages,{'cancel':cancel},8),messages)

    def test_disabled_path_never_initializes_runtime(self):
        from serve.hydra_graph_optional import OptionalGraph
        bridge=OptionalGraph(SimpleNamespace(graph_config=lambda:{}),None,{})
        messages=[{'role':'user','content':'hello'}]
        with patch.object(bridge,'initialize',side_effect=AssertionError('OFF path')):
            self.assertIs(bridge.prepare(messages,{},8),messages)

    def test_initialization_error_falls_back_without_sensitive_error(self):
        from serve.hydra_graph_optional import OptionalGraph
        options=dict(graph_enabled=True,context_compiler_enabled=True)
        bridge=OptionalGraph(SimpleNamespace(graph_config=lambda:options),None,{'mode':'gguf'})
        messages=[{'role':'user','content':'hello'}]
        with patch.object(bridge,'initialize',side_effect=RuntimeError('private path')):
            self.assertIs(bridge.prepare(messages,{},8),messages)
        self.assertNotIn('private path',repr(bridge.snapshot()))
        self.assertEqual(bridge.snapshot()['last']['reason'],'runtime_preparation_unavailable')

    def test_protected_requests_skip_runtime_and_original_identity_preserved(self):
        from serve.hydra_graph_optional import OptionalGraph
        bridge=OptionalGraph(SimpleNamespace(graph_config=lambda:dict(graph_enabled=True,context_compiler_enabled=True)),None,{'mode':'gguf'})
        messages=[{'role':'user','content':'hello'}]
        for options in ({'response_format':{'type':'json_object'}},{'tools':[{}]}):
            with patch.object(bridge,'initialize',side_effect=AssertionError('protected')):
                self.assertIs(bridge.prepare(messages,options,8),messages)

    def test_runtime_template_matches_connector_system_normalization(self):
        from serve.hydra_graph_optional import RuntimeTemplate
        bodies=[]
        def post(path,body):bodies.append((path,body));return {'prompt':'actual template'}
        render=RuntimeTemplate(post,{'chat_template_kwargs':{'enable_thinking':False}})
        messages=[{'role':'system','content':'A'},{'role':'developer','content':'B'},{'role':'user','content':'C'}]
        self.assertEqual(render.render(messages),'actual template')
        self.assertEqual(bodies[0][1]['messages'][0],{'role':'system','content':'A\n\nB'})
        self.assertEqual(messages[1]['role'],'developer')

    def test_configured_bridge_is_ready_before_first_request(self):
        from serve.hydra_graph_optional import OptionalGraph
        bridge=OptionalGraph(SimpleNamespace(),None,{'mode':'gguf'})
        status=bridge.snapshot()
        self.assertTrue(status['enabled'])
        self.assertEqual(status['last']['reason'],'awaiting_request')
        self.assertEqual(status['last']['strategy'],'standard')
