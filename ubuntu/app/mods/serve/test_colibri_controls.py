import unittest
from unittest.mock import Mock, patch
from serve.colibri_controls import require_idle, request, decide


class ColibriControlsTests(unittest.TestCase):
    def test_stop_respects_caller_owned_conversation(self):
        from serve.optional_backends import OptionalBackends
        import threading
        backend=OptionalBackends.__new__(OptionalBackends)
        backend.lock=threading.Lock();backend.request_lock=threading.Lock();backend.conversation_lock=threading.Lock()
        backend.conversation_lock.acquire();backend.cancel_load=threading.Event()
        backend.state={'mode':'api'};backend._stop_child=Mock();backend._release=Mock();backend.status=Mock(return_value={})
        with self.assertRaises(RuntimeError):backend.stop()
        backend.stop(_conversation_owned=True)
        self.assertEqual(backend.state['status'],'idle')
        backend.request_lock.acquire()
        with self.assertRaises(RuntimeError):backend.stop(_conversation_owned=True)

    def test_chat_retains_native_budget_slot_and_thinking(self):
        from serve.optional_inference import LocalOpenAIBackend
        client=LocalOpenAIBackend('http://127.0.0.1:18889/v1');client.max_output_tokens=32768
        response=Mock();response.read.return_value=b'{"choices": [{"message": {"content": "ok"}}]}'
        with patch.object(client,'_request',return_value=(Mock(),response)) as relay:
            list(client.chat([{'role':'user','content':'test'}],'native',8192,cache_slot=0,enable_thinking=False))
        body=relay.call_args.args[2]
        self.assertEqual(body['max_tokens'],8192);self.assertEqual(body['cache_slot'],0);self.assertIs(body['enable_thinking'],False)
        with self.assertRaises(ValueError):list(client.chat([{'role':'user','content':'test'}],'native',16,cache_slot=True))

    def test_active_queued_or_unknown_activity_prevents_stop(self):
        for health in ({}, {'scheduler': {'active': 1, 'queued': 0}}, {'scheduler': {'active': 0, 'queued': 1}}):
            with self.subTest(health=health), self.assertRaises(ValueError):
                require_idle(health)
        require_idle({'scheduler': {'active': 0, 'queued': 0}})

    def test_arbitrary_native_routes_are_rejected_before_network(self):
        workspace=Mock()
        with self.assertRaises(ValueError):request(workspace, '../settings')
        workspace.status.assert_not_called()

    def test_decision_keeps_multiple_questions_and_uses_actual_model(self):
        workspace=Mock();workspace.status.return_value={'model_id':'actual'}
        payload={'state':'document','questions':{'q1':{'type':'choice','instructions':'One?','criteria':{'yes':None,'no':None}},'q2':{'type':'choice','instructions':'Two?','criteria':{'low':None,'high':None}}}}
        with patch('serve.colibri_controls.request',return_value={'answers':{}}) as native:
            decide(workspace,payload)
        self.assertEqual(native.call_args.args[2],dict(payload,model='actual'))

    def test_system_one_accepts_all_native_types_and_options(self):
        workspace=Mock();workspace.status.return_value={'model_id':'native'}
        payload={'state':{'text':'source'},'prefix':'rules','normalize':'mean','pin_state':False,'cache_slot':0,'questions':{'binary':{'type':'noul','instructions':'Urgent?','criteria':{'true':'urgent','false':'routine'}},'scale':{'type':'score','instructions':'Impact?','criteria':['none','blocked']},'choice':{'type':'choice','instructions':'Team?','criteria':{'tech':'technical','billing':None}}}}
        with patch('serve.colibri_controls.request',return_value={}) as native:decide(workspace,payload)
        self.assertEqual(native.call_args.args[2],dict(payload,model='native'))

    def test_system_one_rejects_invalid_native_options_before_network(self):
        workspace=Mock();base={'state':'source','questions':{'q':{'type':'choice','instructions':'Team?','criteria':{'yes':None}}}}
        for change in ({'normalize':'bad'},{'pin_state':'false'},{'cache_slot':True},{'cache_slot':-1},{'prefix':3},{'state':'x'*200001}):
            with self.subTest(change=change),patch('serve.colibri_controls.request') as native:
                with self.assertRaises(ValueError):decide(workspace,dict(base,**change))
                native.assert_not_called()

    def test_system_one_preserves_native_question_and_option_limits(self):
        workspace=Mock();workspace.status.return_value={'model_id':'native'}
        q={'type':'choice','instructions':'Choose','criteria':{str(i):None for i in range(255)}}
        with patch('serve.colibri_controls.request',return_value={}):decide(workspace,{'state':'x','questions':{str(i):q for i in range(64)}})
        with self.assertRaises(ValueError):decide(workspace,{'state':'x','questions':{'q':dict(q,criteria={str(i):None for i in range(256)})}})
