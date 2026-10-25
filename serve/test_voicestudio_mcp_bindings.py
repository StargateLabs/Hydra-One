"""Classify original VoiceStudio responses in our Chat and Harness adapters."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from serve.mcp import DEFAULTS,McpHub,McpServer
from serve.trueforge_setup import bridge_response

def server(name,response):
    value=McpServer(name,{'url':'http://127.0.0.1:3900/mcp'},DEFAULTS)
    value.transport=Mock();value.transport.alive.return_value=True;value.transport.request.return_value=response
    value.status='ready'
    return value

class VoiceMcpBindingsTests(unittest.TestCase):
    def test_chat_marks_explicit_voice_error_and_preserves_native_content(self):
        native={'isError':False,'content':[{'type':'text','text':json.dumps({'error':'pass exactly one audio input'})}]}
        value=server('voicestudio',native);hub=McpHub({});hub._routes={'voicestudio__transcribe':(value,'transcribe')}
        result=hub.call('voicestudio__transcribe',{})
        self.assertFalse(result['ok']);self.assertTrue(result['text'].startswith('error: '))
        self.assertFalse(native['isError']);self.assertIn('pass exactly one audio input',result['text'])
    def test_harness_bridge_marks_the_same_error(self):
        value=server('voicestudio',{'content':[{'type':'text','text':'{"error":"audio required"}'}]})
        hub=SimpleNamespace(routes=lambda:{'voicestudio__transcribe':(value,'transcribe')},settings=DEFAULTS)
        result=bridge_response(hub,{'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'voicestudio__transcribe'}})
        self.assertTrue(result['result']['isError']);self.assertEqual(result['result']['content'][0]['text'],'{"error":"audio required"}')
    def test_reading_a_json_file_is_not_misclassified(self):
        native={'content':[{'type':'text','text':'{"error":"user file contents"}'}]}
        self.assertIs(server('filesystem',native).call('read_file',{},1),native)
    def test_success_and_nested_data_are_preserved(self):
        for text in ['ordinary text containing error','{"text":"error in the transcript"}','{"profile":{"error":"custom metadata"}}']:
            native={'content':[{'type':'text','text':text}]}
            self.assertIs(server('voicestudio',native).call('list_voices',{},1),native)
    def test_recovery_call_is_success_after_invalid_input(self):
        value=server('voicestudio',{})
        value.transport.request.side_effect=[{'content':[{'type':'text','text':'{"error":"audio required"}'}]},{'content':[{'type':'text','text':'{"status":"ok"}'}]}]
        self.assertTrue(value.call('transcribe',{},1)['isError']);self.assertFalse(value.call('check_health',{},1).get('isError',False))
    def test_graphify_explicit_execution_error_is_not_a_success(self):
        native={'isError':False,'content':[{'type':'text','text':'Error executing graph_stats: invalid project path'}]}
        value=server('graphify',native);hub=McpHub({});hub._routes={'graphify__graph_stats':(value,'graph_stats')}
        result=hub.call('graphify__graph_stats',{'project_path':3})
        self.assertFalse(result['ok']);self.assertFalse(native['isError'])
    def test_graphify_success_text_and_other_servers_remain_unchanged(self):
        for name,text in [('graphify','Nodes: 1\nError executing appears in user metadata'),('graphify','Error executing a different_tool: metadata'),('filesystem','Error executing graph_stats: file contents')]:
            native={'content':[{'type':'text','text':text}]}
            self.assertIs(server(name,native).call('graph_stats',{},1),native)

if __name__=='__main__':unittest.main()
