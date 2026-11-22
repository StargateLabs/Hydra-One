import unittest
from types import SimpleNamespace
from serve.harness_model import local_selection, resolve_request


class HarnessModelTests(unittest.TestCase):
    def service(self, state):
        return SimpleNamespace(model='actual-qwen',engine=SimpleNamespace(max_context=8192),
            model_names=lambda:['actual-qwen','strata'],optional_backends=SimpleNamespace(status=lambda:state))

    def test_alias_uses_ready_optional_and_real_budget(self):
        svc=self.service({'status':'ready','public_model':'local/qwen','context_per_slot':4096})
        req=resolve_request(svc,{'model':'strata','max_tokens':16384})
        self.assertEqual(req,{'model':'local/qwen','max_tokens':1024})
        self.assertEqual(local_selection(svc)['context'],4096)

    def test_primary_and_explicit_selection_do_not_silently_fall_back(self):
        svc=self.service({'status':'idle'})
        self.assertEqual(resolve_request(svc,{'model':'strata'})['model'],'actual-qwen')
        self.assertEqual(resolve_request(svc,{'model':'actual-qwen','max_tokens':3000})['max_tokens'],3000)
        for model in ('stale-qwen','local/stale'):
            with self.assertRaises(ValueError):resolve_request(svc,{'model':model})

    def test_engine_formats_and_false_tool_capability(self):
        for mode in ('gguf','safetensors','api'):
            svc=self.service({'status':'ready','mode':mode,'public_model':'local/'+mode,'context_per_slot':32768,
                              'capabilities':{'tool_calling':False if mode=='safetensors' else 'model_dependent'}})
            self.assertEqual(resolve_request(svc,{'model':'strata'})['model'],'local/'+mode)
            if mode=='safetensors':
                with self.assertRaises(ValueError):resolve_request(svc,{'model':'strata','tools':[{'name':'read'}]})
                self.assertFalse(local_selection(svc)['tool_calling'])

    def test_dsh_hermes_trueforge_managed_binding_config(self):
        import tempfile, json
        from pathlib import Path
        from serve.agent_harness import AgentHarness
        import yaml
        with tempfile.TemporaryDirectory() as folder:
            for kind in ('dsh','hermes','trueforge'):
                harness=AgentHarness(folder,kind=kind,binary='fixture',api_key='fixture-auth',
                    base_url='http://127.0.0.1:8090/v1',model_context=8192,model_output=2048,mcp_servers={})
                if kind=='hermes':
                    harness.home().mkdir(parents=True)
                    harness.config_path().write_text('model:\n  default: stale\n  provider: remote\ncustom_preserved: yes\n')
                path=harness.write_config()
                if kind=='dsh':
                    config=yaml.safe_load(path.read_text());provider=config[0]['config']['providers']['strata']
                    self.assertEqual(provider['models'][0]['maxOutputTokens'],2048)
                    self.assertEqual(harness.environment()['STRATA_API_KEY'],'fixture-auth')
                elif kind=='hermes':
                    config=yaml.safe_load(path.read_text());self.assertEqual(config['model']['default'],'strata')
                    self.assertEqual(config['model']['context_length'],8192);self.assertTrue(config['custom_preserved'])
                    from unittest.mock import patch
                    with patch('serve.hermes_integration.runtime',return_value={'source':Path(folder),'site':Path(folder)/'site'}):
                        command=harness.command()
                    self.assertNotIn('-c',command)
                    self.assertEqual(command[command.index('-m')+1],'hermes_cli.main')
                    self.assertIn('--no-open',command)
                else:
                    config=json.loads(path.read_text());self.assertEqual(config['model'],'strata')
                    self.assertEqual(config['context'],8192)


if __name__=='__main__':unittest.main()

class ClaudeBindingTests(unittest.TestCase):
    def test_cached_claude_tracks_current_local_model_budget_without_rebinding_busy_run(self):
        import threading
        from serve.server import agent_harness_for
        harness=SimpleNamespace(model='stale',context_budget=131072,output_budget=2048,status=lambda:{'busy':False})
        svc=SimpleNamespace(status_lock=threading.Lock(),agent_harness_claude=harness,api_key=None,model='native',engine=SimpleNamespace(max_context=8192),optional_backends=SimpleNamespace(status=lambda:{'status':'ready','public_model':'local/small','context_per_slot':4096}))
        self.assertIs(agent_harness_for(svc,'claude'),harness)
        self.assertEqual(harness.model,'strata');self.assertEqual(harness.context_budget,4096);self.assertEqual(harness.output_budget,1024)
        harness.status=lambda:{'busy':True};harness.model='explicit-running'
        agent_harness_for(svc,'claude');self.assertEqual(harness.model,'explicit-running')

class CompactBridgeTests(unittest.TestCase):
    def test_schema_constraints_and_original_description_are_preserved(self):
        from serve.trueforge_setup import bridge_tools
        schema={'type':'object','required':['confirm'],'properties':{'confirm':{'type':'boolean','const':True,'description':'safe '*300}}}
        hub=SimpleNamespace(template_tools=lambda:[{'name':'test','description':'detail '*1000,'parameters':schema}])
        result=bridge_tools(hub)[0]
        self.assertEqual(len(result['description']),256)
        self.assertEqual(result['inputSchema']['required'],['confirm'])
        self.assertTrue(result['inputSchema']['properties']['confirm']['const'])
        self.assertEqual(len(schema['properties']['confirm']['description']),1500)
