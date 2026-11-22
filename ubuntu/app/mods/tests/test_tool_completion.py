import threading,unittest
from types import SimpleNamespace
from serve.frontend import OutputParser,ToolCall,Event
from serve.server import run_with_mcp
class CompletionTests(unittest.TestCase):
 def test_whole_function_without_outer_close_keeps_arguments(self):
  p=OutputParser(thinking=False,tools=[{"name":"read","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}],stream_tools=True)
  p.feed('<tool_call><function=read><parameter=path>README.md</parameter></function>')
  calls=[x.call for x in p.finish() if x.kind=="tool_call"]
  self.assertEqual(calls[0].arguments,{"path":"README.md"})
 def test_complete_call_cut_at_the_token_limit_is_not_executed(self):
  # 0.2.9 executes a call only when the run finished with "stop": a call cut at the
  # token limit may be malformed, so the live line's "execute anyway" is not carried.
  call=ToolCall("read",{"path":"README.md"});executed=[];runs=[0]
  def run(*a, **kw):
   runs[0]+=1
   if runs[0]==1:
    yield "event",Event("tool_start",call=call);yield "event",Event("tool_call",call=call)
   else:yield "event",Event("content",text="Answer")
   yield "done",{"completion_tokens":3,"finish":"length" if runs[0]==1 else "stop"}
  hub=SimpleNamespace(settings={"max_rounds":3},routes=lambda:{},call=lambda *a:(executed.append(a) or {"ok":True,"text":"data","chars":4,"truncated":False,"ms":1}))
  svc=SimpleNamespace(run=run,prepare=lambda *a:([1],False,10))
  events=list(run_with_mcp(svc,hub,[],[],{},[1],False,10,10,{},threading.Event(),{"read"}))
  self.assertEqual(len(executed),0)
 def test_incomplete_call_is_never_executed(self):
  call=ToolCall("read",{});executed=[]
  def run(*a, **kw):
   yield "event",Event("tool_start",call=call);yield "done",{"completion_tokens":3,"finish":"length"}
  hub=SimpleNamespace(settings={"max_rounds":3},call=lambda *a:executed.append(a))
  events=list(run_with_mcp(SimpleNamespace(run=run),hub,[],[],{},[1],False,10,10,{},threading.Event(),{"read"}))
  self.assertFalse(executed)
if __name__=="__main__":unittest.main()
