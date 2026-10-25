import json,urllib.request
from pathlib import Path
root=Path.cwd();token=(root/'data/agent-harness/trueforge-mcp-token').read_text().strip()
rows=[]
for name,args in [('filesystem__list_allowed_directories',{}),('filesystem__read_file',{'path':str(root/'AGENTS.md'),'head':2}),('memory__read_graph',{}),('time__get_current_time',{'timezone':'Europe/Rome'}),('strata_diagnostics__read_prepared_models',{})]:
 request=urllib.request.Request('http://127.0.0.1:8090/harness/mcp',data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
 with urllib.request.urlopen(request,timeout=20) as response:result=json.load(response)
 assert not result.get('error') and not result.get('result',{}).get('isError'),name
 rows.append({'tool':name,'passed':True})
proof={'passed':True,'port':8090,'calls':rows,'scope':'Actual read-only MCP calls; no claim of automatic model tool selection'}
(root/'output/verification/localai-mcp-real.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');print('Five real non-weather MCP calls passed')
