import unittest
from types import SimpleNamespace
from serve.trueforge_setup import bridge_response
class TrueForgeBridgeTests(unittest.TestCase):
 def test_protocol_and_local_tools(self):
  hub=SimpleNamespace(template_tools=lambda:[{'name':'filesystem__read_file','description':'local','parameters':{'type':'object'}}])
  self.assertEqual(bridge_response(hub,{'jsonrpc':'2.0','id':1,'method':'tools/list'})['result']['tools'][0]['name'],'filesystem__read_file')
  self.assertIsNone(bridge_response(None,{'jsonrpc':'2.0','method':'notifications/initialized'}))
 def test_unknown_and_invalid(self):
  with self.assertRaises(ValueError):bridge_response(None,{})
  self.assertEqual(bridge_response(None,{'jsonrpc':'2.0','id':1,'method':'missing'})['error']['code'],-32601)
 def test_native_call_returns_original_result(self):
  server=SimpleNamespace(call=lambda tool,args,timeout:{'content':[{'type':'text','text':'local result'}]})
  hub=SimpleNamespace(routes=lambda:{'memory__read_graph':(server,'read_graph')},settings={'timeout_s':10})
  response=bridge_response(hub,{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'memory__read_graph','arguments':{}}})
  self.assertEqual(response['result']['content'][0]['text'],'local result')
 def test_shared_bridge_preserves_readonly_annotations(self):
  server=SimpleNamespace(tools=[{'name':'read_file','annotations':{'readOnlyHint':True}}])
  hub=SimpleNamespace(routes=lambda:{'filesystem__read_file':(server,'read_file')},template_tools=lambda:[{'name':'filesystem__read_file','description':'Read','parameters':{'type':'object'}}])
  result=bridge_response(hub,{'jsonrpc':'2.0','id':1,'method':'tools/list'})
  self.assertTrue(result['result']['tools'][0]['annotations']['readOnlyHint'])
if __name__=='__main__':unittest.main()
