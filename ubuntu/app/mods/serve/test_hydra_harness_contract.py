import tempfile
import threading
import unittest
from types import SimpleNamespace
from serve.harness_model import local_selection,resolve_request
from serve.optional_backends import OptionalBackends
from serve.optional_inference import BackendError


class HydraHarnessContract(unittest.TestCase):
    def test_hydra_manager_mcp_round_trip_preserves_tool_identity(self):
        from serve.optional_tools import chat_with_tools
        with tempfile.TemporaryDirectory() as root:
            manager=OptionalBackends(root,discover_models=False)
            manager.state.update(status='ready',mode='gguf',engine_addon='hydra-one',
                                 backend='HYDRA ONE',api_model='optional-model',model='fixture')
            requests=[];executed=[]
            def chat(messages,model,max_tokens,**options):
                requests.append((messages,options))
                message={'role':'assistant','content':'done'}
                if len(requests)==1:
                    message={'role':'assistant','content':None,'tool_calls':[
                        {'id':'call-1','type':'function','function':
                         {'name':'fixture__read','arguments':'{"value":7}'}}]}
                yield dict(id='fixture',created=1,model=model,choices=[
                    {'message':message,'finish_reason':'tool_calls' if len(requests)==1 else 'stop'}],
                    usage={'completion_tokens':1})
            manager.client=SimpleNamespace(chat=chat)
            def call(name,args,cancel):
                executed.append((name,args))
                return dict(ok=True,text='7',chars=1,truncated=False,ms=0)
            hub=SimpleNamespace(settings={'max_rounds':2},call=call,
                template_tools=lambda:[{'name':'fixture__read','description':'fixture',
                    'parameters':{'type':'object','properties':{'value':{'type':'integer'}}}}])
            packets=list(chat_with_tools(manager,hub,{'messages':[{'role':'user','content':'read'}],
                'stream':False,'max_tokens':32},threading.Event()))
            self.assertEqual(executed,[('fixture__read',{'value':7})])
            self.assertEqual(len(requests),2)
            self.assertEqual(requests[1][0][-1],{'role':'tool','tool_call_id':'call-1','content':'7'})
            self.assertEqual([p['strata_mcp']['id'] for p in packets if 'strata_mcp' in p],['call-1','call-1'])
            self.assertTrue(any(p['choices'][0]['delta'].get('content')=='done' for p in packets))
            self.assertFalse(manager.request_lock.locked())
            manager.client=None

    def test_binding_identifies_engine_without_claiming_model_tool_support(self):
        state=dict(status='ready',public_model='local/fixture',context_per_slot=4096,
                   backend='HYDRA ONE',engine_addon='hydra-one',
                   capabilities={'tool_calling':'model_dependent','mcp_bridge':True})
        svc=SimpleNamespace(optional_backends=SimpleNamespace(status=lambda:state))
        selection=local_selection(svc)
        self.assertEqual(selection['engine_addon'],'hydra-one')
        self.assertEqual(selection['backend'],'HYDRA ONE')
        self.assertEqual(selection['tool_calling'],'model_dependent')
        self.assertEqual(resolve_request(svc,{'model':'strata','max_tokens':9999})['max_tokens'],1024)

    def test_partial_tool_stream_is_never_replayed_on_context_error(self):
        with tempfile.TemporaryDirectory() as root:
            manager=OptionalBackends(root,discover_models=False)
            manager.state.update(status='ready',mode='gguf',engine_addon='hydra-one',
                                 api_model='optional-model',model='fixture')
            calls=[]
            def chat(*args,**kwargs):
                calls.append(args)
                yield {'choices':[{'delta':{'tool_calls':[{'id':'call-1'}]}}]}
                raise BackendError('context exceeded')
            manager.client=SimpleNamespace(chat=chat)
            events=manager.chat({'messages':[{'role':'user','content':'old'},
                  {'role':'assistant','content':'previous'},
                  {'role':'user','content':'new'}]},threading.Event())
            next(events)
            with self.assertRaises(BackendError):next(events)
            self.assertEqual(len(calls),1)
            self.assertFalse(manager.request_lock.locked())
            manager.client=None
