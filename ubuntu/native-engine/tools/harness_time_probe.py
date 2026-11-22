"""Original harness probe with isolated home and a read-only time-only gateway."""
import base64,json,re,socket,sqlite3,threading,urllib.request,urllib.error
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

def free_port():
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

class TimeGateway:
 def __init__(self,root,base,*,allow_code_mode=False,allow_deferred=False):
  token=(Path(root)/'data/agent-harness/trueforge-mcp-token').read_text(encoding='utf-8').strip();owner=self;self.calls=[];self.errors=[];self.requests=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):self.forward()
   def do_POST(self):self.forward()
   def forward(self):
    try:
     length=int(self.headers.get('Content-Length',0))
     if not 0<=length<=4*1024**2:raise ValueError('Request exceeds probe limit')
     raw=self.rfile.read(length) if length else None;payload=json.loads(raw) if raw else None
     owner.requests.append({'path':self.path,'method':self.command});is_mcp=self.path.split('?',1)[0]=='/harness/mcp';headers={'Content-Type':'application/json','Origin':base}
     if self.command=='GET' and self.path in ('/api/v1/models','/api/tags','/props','/version','/v1/props'):
      # Native provider detection tries several incompatible local protocols.
      # A normal 404 is expected; it must not abort an OpenAI-compatible turn.
      body=b'{"error":{"message":"This probe uses the OpenAI-compatible API"}}';self.send_response(404);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
     if is_mcp:
      headers['Authorization']='Bearer '+token
      if payload and payload.get('method')=='tools/call' and payload.get('params',{}).get('name')!='time__get_current_time':raise ValueError('Probe permits only the read-only time tool')
     elif not self.path.startswith('/v1/'):raise ValueError('Unsupported probe route')
     if payload and not is_mcp and isinstance(payload.get('tools'),list):
      owner.requests[-1]['tools']=[tool.get('function',{}).get('name') for tool in payload['tools']]
      owner.requests[-1]['execute_schema']=next((tool['function'] for tool in payload['tools'] if tool.get('function',{}).get('name')=='execute'),None)
      payload['tools']=[tool for tool in payload['tools'] if tool.get('function',{}).get('name','').endswith('get_current_time') or (allow_code_mode and tool.get('function',{}).get('name')=='execute') or (allow_deferred and tool.get('function',{}).get('name') in ('tool_search','tool_describe','tool_call'))]
      payload['max_tokens']=min(int(payload.get('max_tokens') or 512),512)
      raw=json.dumps(payload).encode()
     request=urllib.request.Request(base+self.path,data=raw,headers=headers,method=self.command)
     with urllib.request.urlopen(request,timeout=75) as response:body=response.read(16*1024**2);content_type=response.headers.get('Content-Type','application/json')
     if is_mcp:
      reply=json.loads(body)
      if payload and payload.get('method')=='tools/list':
       reply['result']['tools']=[tool for tool in reply.get('result',{}).get('tools',[]) if tool['name']=='time__get_current_time'];body=json.dumps(reply).encode()
      if payload and payload.get('method')=='tools/call':owner.calls.append({'name':payload['params']['name'],'arguments':payload['params'].get('arguments'),'response':reply})
     elif payload and self.path.endswith('/chat/completions'):
      # Buffer probe completions and reject any tool outside the authorized set
      # before a native agent can execute it. This is not a performance benchmark.
      messages=[]
      if 'text/event-stream' in content_type:
       for line in body.decode('utf-8').splitlines():
        if line.startswith('data: ') and line[6:]!='[DONE]':messages.append(json.loads(line[6:]))
      else:messages=[json.loads(body)]
      names={};arguments={}
      for message in messages:
       for choice in message.get('choices',[]):
        for call in (choice.get('delta') or choice.get('message') or {}).get('tool_calls',[]):
         name=call.get('function',{}).get('name','');index=call.get('index',0);names[index]=names.get(index,'')+name;arguments[index]=arguments.get(index,'')+call.get('function',{}).get('arguments','')
      for index,name in names.items():
       if name.endswith('get_current_time'):continue
       if allow_deferred and name in ('tool_search','tool_describe','tool_call'):
        args=json.loads(arguments[index])
        if name=='tool_search' and set(args)<= {'queries','limit'}:
         queries=args.get('queries',[]);queries=[queries] if isinstance(queries,str) else queries
         if isinstance(queries,list) and 0<len(queries)<=3 and all(isinstance(query,str) and len(query)<=200 for query in queries):continue
        if name=='tool_describe' and set(args)=={'names'}:
         targets=args['names'];targets=[targets] if isinstance(targets,str) else targets
         if isinstance(targets,list) and len(targets)==1 and targets[0].endswith('get_current_time'):continue
        if name=='tool_call' and set(args)=={'calls'}:
         calls=args['calls']
         if isinstance(calls,list) and len(calls)==1 and calls[0].get('name','').endswith('get_current_time') and calls[0].get('arguments')=={'timezone':'Europe/Rome'}:continue
        raise ValueError('Deferred call outside the read-only time probe')
       if allow_code_mode and name=='execute':
        code=json.loads(arguments[index]).get('code','')
        # Exact read-only call only. No loops, fetch, imports, writes or extra code.
        pattern=r'''\s*(?:return\s+)?await\s+tools\.stargatelab(?:\.time__get_current_time|\[(['"])time__get_current_time\1\])\(\s*\{\s*(?:['"]?timezone['"]?)\s*:\s*(['"])Europe/Rome\2\s*\}\s*\)\s*;?\s*'''
        if re.fullmatch(pattern,code):continue
        raise ValueError('Native Code Mode requested code outside the exact read-only time call: '+code[:500])
       raise ValueError('Model requested a tool outside the time-only probe')
     self.send_response(200);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    except (BrokenPipeError,ConnectionResetError) as error:owner.errors.append(self.path+': client disconnected')
    except Exception as error:
     owner.errors.append(self.path+': '+str(error));body=json.dumps({'error':{'message':str(error)}}).encode()
     try:
      self.send_response(400);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
     except (BrokenPipeError,ConnectionResetError):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.url=f'http://127.0.0.1:{self.server.server_port}'
  threading.Thread(target=self.server.serve_forever,daemon=True).start()
 def close(self):self.server.shutdown();self.server.server_close()

def native_call(harness,path,payload=None,timeout=10):
 headers={'Content-Type':'application/json'}
 if harness.kind=='opencode':headers['Authorization']='Basic '+base64.b64encode(('opencode:'+harness.password).encode()).decode()
 request=urllib.request.Request(f'http://127.0.0.1:{harness.port}'+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
 with urllib.request.urlopen(request,timeout=timeout) as response:
  raw=response.read(8*1024**2);return json.loads(raw) if response.headers.get_content_type()=='application/json' else raw.decode('utf-8')

def opencode_final_text(folder,session):
 """Read only this proof home's original native session, after child shutdown."""
 database=(Path(folder)/'data/opencode-home/data/opencode/opencode.db').resolve()
 with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
  rows=connection.execute('SELECT data FROM session_message WHERE session_id=? AND type=? ORDER BY seq DESC LIMIT 1',(session,'assistant')).fetchall()
 if not rows:return ''
 message=json.loads(rows[0][0])
 if message.get('finish')!='stop' or not message.get('time',{}).get('completed'):return ''
 return '\n'.join(item.get('text','') for item in message.get('content',[]) if item.get('type')=='text')

def dsh_final_text(page):
 """Require original completed turn and its final assistant text."""
 events=[row['event'] for row in page.get('records',[]) if row.get('type')=='event']
 if not any(event.get('type')=='turn/end' and event.get('data',{}).get('reason',{}).get('kind')=='completed' for event in events):return ''
 messages=[event['data']['message'] for event in events if event.get('type')=='assistant/message']
 if not messages:return ''
 return '\n'.join(item.get('text','') for item in messages[-1].get('content',[]) if item.get('type')=='text')
