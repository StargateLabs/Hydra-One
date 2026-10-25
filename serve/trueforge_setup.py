"""Connect official TrueForge UI to Strata and the existing, authenticated MCP hub."""
import json,secrets,threading,urllib.request,urllib.error
from pathlib import Path
_TOKEN_LOCK=threading.Lock()
_BROWSER_LOCK=threading.Lock()
_MEMORY_LOCK=threading.Lock()
def bridge_token(root):
 path=Path(root)/'data/agent-harness/trueforge-mcp-token'
 with _TOKEN_LOCK:
  try:return path.read_text().strip()
  except FileNotFoundError:
   path.parent.mkdir(parents=True,exist_ok=True);token=secrets.token_urlsafe(32)
   with path.open('x') as stream:stream.write(token)
   return token

def compact_schema_metadata(value):
 if isinstance(value,list):return [compact_schema_metadata(item) for item in value]
 if not isinstance(value,dict):return value
 return {key:(item[:256] if key=='description' and isinstance(item,str) else compact_schema_metadata(item)) for key,item in value.items()}

def bridge_tools(hub,prefix=None):
 if not hub:return []
 routes=hub.routes() if hasattr(hub,'routes') else {};tools=[]
 for item in hub.template_tools():
  if prefix and not item['name'].startswith(prefix):continue
  row={'name':item['name'],'description':item['description'][:256],'inputSchema':compact_schema_metadata(item['parameters'])}
  server,original=routes.get(item['name'],(None,None))
  metadata=next((t for t in getattr(server,'tools',[]) if t.get('name')==original),{})
  for key in ('title','annotations'):
   if key in metadata:row[key]=metadata[key]
  tools.append(row)
 return tools

def bridge_response(hub,request,prefix=None):
 if not isinstance(request,dict) or request.get('jsonrpc')!='2.0':raise ValueError('Invalid JSON-RPC request')
 identity=request.get('id');method=request.get('method');params=request.get('params') or {}
 if identity is None:return None
 try:
  if method=='initialize':result={'protocolVersion':params.get('protocolVersion','2025-03-26'),'capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'StargateLab local MCP','version':'1.0'}}
  elif method=='ping':result={}
  elif method=='tools/list':result={'tools':bridge_tools(hub,prefix)}
  elif method=='tools/call':
   if not hub:raise ValueError('MCP hub not ready')
   name=params.get('name');routes=hub.routes();server,tool=routes.get(name,(None,None))
   if server is None or prefix and not name.startswith(prefix):raise ValueError('Unknown MCP tool')
   if name.startswith('browser__'):
    with _BROWSER_LOCK:result=server.call(tool,params.get('arguments') or {},float(hub.settings['timeout_s']))
   elif name.startswith('memory__'):
    with _MEMORY_LOCK:result=server.call(tool,params.get('arguments') or {},float(hub.settings['timeout_s']))
   else:result=server.call(tool,params.get('arguments') or {},float(hub.settings['timeout_s']))
  elif method in ('resources/list','resources/templates/list','prompts/list'):result={'resources':[]} if method=='resources/list' else {'resourceTemplates':[]} if method=='resources/templates/list' else {'prompts':[]}
  else:return {'jsonrpc':'2.0','id':identity,'error':{'code':-32601,'message':'Unsupported method'}}
  return {'jsonrpc':'2.0','id':identity,'result':result}
 except Exception as error:return {'jsonrpc':'2.0','id':identity,'error':{'code':-32602,'message':str(error)}}

def configure(harness):
 base=f'http://127.0.0.1:{harness.port}'
 def call(path,payload=None):
  request=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'},method='PUT' if payload is not None else 'GET')
  try:
   with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
  except urllib.error.HTTPError as error:
   raise RuntimeError('TrueForge configuration rejected: '+error.read(4096).decode(errors='replace')) from error
 model={'manifest':{'type':'custom','name':'strata-local','base_url':harness.base_url,'auth':{'api_key':harness.environment()['STRATA_API_KEY']},'models':[{'name':'strata','model_id':harness.model_id,'properties':{'context_length':harness.model_context,'max_output_tokens':harness.model_output}}]}}
 call('/api/v1/settings/model-providers',model)
 bridge={'manifest':{'type':'remote','name':'stargatelab-pc','url':harness.base_url.removesuffix('/v1')+'/harness/mcp','description':'Local PC tools, memory and all MCP tools already connected in StargateLab','auth':{'type':'header','headers':{'Authorization':'Bearer '+bridge_token(harness.root)}}}}
 call('/api/v1/settings/mcp-servers',bridge)
 return {'local_model_configured':True,'local_mcp_configured':True}
