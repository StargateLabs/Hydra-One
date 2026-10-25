import urllib.request,json,uuid
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088';token=(root/'data/agent-harness/trueforge-mcp-token').read_text().strip()
def call(path,method,params=None):
 req=urllib.request.Request(base+path,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=40) as response:data=json.load(response)
 if data.get('error'):raise RuntimeError(data['error'])
 result=data['result'];assert not result.get('isError'),str(result)[:200];return result
alltools=call('/harness/mcp','tools/list')['tools'];browser=call('/harness/browser-mcp','tools/list')['tools'];memory=call('/harness/memory-mcp','tools/list')['tools'];print('Shared tools:',len(alltools),'browser:',len(browser),'memory:',len(memory))
assert browser and all(t['name'].startswith('browser__') for t in browser);assert len(memory)==9
result=call('/harness/browser-mcp','tools/call',{'name':'browser__browser_navigate','arguments':{'url':base+'/health'}});print('Actual Chromium navigation passed')
call('/harness/browser-mcp','tools/call',{'name':'browser__browser_close','arguments':{}})
name='__stargatelab_shared_probe_'+uuid.uuid4().hex
before=call('/harness/memory-mcp','tools/call',{'name':'memory__read_graph','arguments':{}})
try:
 call('/harness/mcp','tools/call',{'name':'memory__create_entities','arguments':{'entities':[{'name':name,'entityType':'verification','observations':['Temporary local shared-memory check']}]}})
 found=call('/harness/memory-mcp','tools/call',{'name':'memory__search_nodes','arguments':{'query':name}})
 assert name in json.dumps(found);print('Shared memory write/read passed')
finally:call('/harness/memory-mcp','tools/call',{'name':'memory__delete_entities','arguments':{'entityNames':[name]}})
after=call('/harness/memory-mcp','tools/call',{'name':'memory__read_graph','arguments':{}});assert before==after,'Existing memory changed'
history=call('/harness/mcp','tools/call',{'name':'strata_diagnostics__list_harness_conversations','arguments':{}})
report={'passed':True,'total_tools':len(alltools),'browser_tools':len(browser),'memory_tools':len(memory),'real_browser_navigation':True,'shared_memory_write_read':True,'existing_memory_preserved':True,'cross_history_available':bool(history.get('content')),'scope':'Real shared Chromium local navigation, shared memory write/read with temporary entity removed, original graph unchanged, cross-harness history tool'}
(root/'output/verification/harness-shared-browser-memory-real.json').write_text(json.dumps(report,indent=2));print(report)
