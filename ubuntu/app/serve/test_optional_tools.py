import threading, unittest
from types import SimpleNamespace
from serve.optional_tools import chat_with_tools
from serve.web_tools import read_public
from unittest.mock import patch
class Tests(unittest.TestCase):
 def test_round_trip(self):
  class Manager:
   def chat(self,p,c):
    if len(p['messages'])==1:
     msg={'role':'assistant','content':None,'tool_calls':[{'id':'x','type':'function','function':{'name':'search','arguments':'{"query":"test"}'}}]}
    else:
     self.messages=p['messages'];msg={'role':'assistant','content':'source checked'}
    yield dict(id='x',created=1,model='local/test',choices=[{'message':msg,'finish_reason':'stop'}],usage={'completion_tokens':2,'prompt_tokens':3,'total_tokens':5})
  m=Manager();h=SimpleNamespace(settings={'max_rounds':2},template_tools=lambda:[{'name':'search','parameters':{}}],call=lambda *a:dict(ok=True,text='result',chars=6,truncated=False,ms=1))
  events=list(chat_with_tools(m,h,{'messages':[{'role':'user','content':'search'}],'max_tokens':20},threading.Event()))
  self.assertEqual(m.messages[-1]['tool_call_id'],'x');self.assertEqual(events[-1]['usage']['completion_tokens'],4)
  self.assertEqual(sum('strata_mcp' in e for e in events),2)
 def test_tool_selection_excludes_unselected_tools(self):
  seen=[]
  class Manager:
   def chat(self,p,c):
    seen.extend(t['function']['name'] for t in p['tools'])
    yield dict(id='x',created=1,model='local/test',choices=[{'message':{'role':'assistant','content':'done'},'finish_reason':'stop'}],usage={'completion_tokens':1})
  hub=SimpleNamespace(settings={'max_rounds':2},template_tools=lambda:[{'name':'one'},{'name':'two'}])
  list(chat_with_tools(Manager(),hub,{'messages':[{'role':'user','content':'test'}],'strata_tools':['one'],'max_tokens':10},threading.Event()))
  self.assertEqual(seen,['one'])
 def test_streaming_does_not_duplicate_text_and_collects_usage_only_chunk(self):
  class Manager:
   def chat(self,p,c):
    base=dict(id='x',created=1,model='local/test',object='chat.completion.chunk')
    yield {**base,'choices':[{'index':0,'delta':{'content':'Hello'},'finish_reason':None}]}
    yield {**base,'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
    yield {**base,'choices':[],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}}
  hub=SimpleNamespace(settings={'max_rounds':2},template_tools=lambda:[])
  result=list(chat_with_tools(Manager(),hub,{'messages':[{'role':'user','content':'Hi'}],'stream':True,'max_tokens':20},threading.Event()))
  self.assertEqual(''.join(e['choices'][0]['delta'].get('content','') for e in result),'Hello')
  self.assertEqual(result[-1]['usage']['completion_tokens'],1)
 def test_private_url(self):
  with self.assertRaises(ValueError):read_public('http://localhost/test')
  with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
   with self.assertRaises(ValueError):read_public('https://example.com')
class TemplateArgumentsTests(unittest.TestCase):
 def test_strings_normalized_without_mutation(self):
  import tempfile,json
  from pathlib import Path
  from serve.frontend import ChatTemplate
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'template.jinja';path.write_text("{{messages[0].tool_calls[0].function.arguments.query}}",encoding='utf-8')
   template=ChatTemplate(path)
   for value in ['{"query":"web"}',json.dumps('{"query":"web"}')]:
    messages=[{'tool_calls':[{'function':{'name':'search','arguments':value}}]}]
    self.assertEqual(template.render(messages),'web');self.assertEqual(messages[0]['tool_calls'][0]['function']['arguments'],value)
if __name__=='__main__':unittest.main()

class NativeCapabilityTests(unittest.TestCase):
 def test_plain_native_chat_does_not_receive_incompatible_mcp_tools(self):
  seen=[]
  class Manager:
   def status(self):return dict(mode='safetensors',capabilities={'tool_calling':False})
   def chat(self,p,c):
    seen.extend(p['tools'])
    yield dict(id='x',created=1,model='local/test',choices=[{'message':{'role':'assistant','content':'Hello'},'finish_reason':'stop'}],usage={'completion_tokens':1})
  hub=SimpleNamespace(settings={'max_rounds':2},template_tools=lambda:[{'name':'search'}])
  result=list(chat_with_tools(Manager(),hub,{'messages':[{'role':'user','content':'Hi'}]},threading.Event()))
  self.assertEqual(seen,[]);self.assertEqual(result[0]['choices'][0]['delta']['content'],'Hello')
