"""Original Hermes dashboard websocket turn, isolated home and read-only MCP."""
import argparse,asyncio,json,secrets,sys,time,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.agent_harness import AgentHarness
from serve.hermes_integration import runtime
from tools.harness_time_probe import TimeGateway,free_port
root=Path(__file__).resolve().parents[1];base='http://127.0.0.1:8090'
folder=root/'output/verification/open-plans-20261012/hermes-native-time';folder.mkdir(parents=True,exist_ok=True)
def call(path,payload=None):
 request=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
report={'passed':False,'scope':'One original Hermes dashboard websocket time-tool turn; not all-model certification'}
harness=None;gateway=None;started=False
async def native_turn(token):
 import websockets
 native_base=f'http://127.0.0.1:{harness.port}';frames=[];identity=0
 async with websockets.connect(f'ws://127.0.0.1:{harness.port}/api/ws?token={token}',origin=native_base,open_timeout=15,max_size=4*1024**2) as websocket:
  async def rpc(method,params):
   nonlocal identity
   identity+=1;current=identity
   await websocket.send(json.dumps({'jsonrpc':'2.0','id':current,'method':method,'params':params}))
   while True:
    frame=json.loads(await asyncio.wait_for(websocket.recv(),timeout=20));frames.append(frame)
    if frame.get('id')==current:
     if frame.get('error'):raise RuntimeError(json.dumps(frame['error']))
     return frame['result']
  created=await rpc('session.create',{'cwd':str(folder),'cwd_explicit':True,'model':'strata','provider':'custom','close_on_disconnect':True});session=created['session_id'];report['session_id']=session
  report['prompt_accepted']=await rpc('prompt.submit',{'session_id':session,'text':'Use tool_search with queries ["time get_current_time"] to find the deferred MCP time tool. Use tool_describe if needed, then tool_call with timezone Europe/Rome. Report the returned time in one sentence. Do not read, write or edit files or run commands.'})
  deadline=time.monotonic()+75
  while time.monotonic()<deadline:
   frame={}
   try:frame=json.loads(await asyncio.wait_for(websocket.recv(),timeout=1));frames.append(frame)
   except asyncio.TimeoutError:pass
   if frame.get('method')=='event' and frame.get('params',{}).get('type')=='message.complete':
    payload=frame['params'].get('payload',{});report['final_assistant_text']=payload.get('text');report['native_completed']=payload.get('status')=='complete';break
   if gateway.errors:break
   if gateway.calls and not harness.status().get('busy'):break
  report['native_frames']=frames;report['tool_calls']=gateway.calls;report['gateway_errors']=gateway.errors;report['requests']=gateway.requests
  successful=[item for item in gateway.calls if 'result' in item['response'] and not item['response']['result'].get('isError') and item['response']['result'].get('content')]
  report['passed']=bool(successful) and report.get('native_completed') and bool(report.get('final_assistant_text')) and not gateway.errors and not harness.status().get('busy')
try:
 assert call('/metrics')['live']['state']=='unloaded' and call('/inference-backends')['status']=='idle','Existing model active'
 rows=json.loads((folder.parent/'model-compatibility-matrix.json').read_text(encoding='utf-8'))['models'];model=next(row['path'] for row in rows if row['name']=='Qwen3.5-4B-UD-Q4_K_XL')
 call('/inference-backends/start',{'mode':'gguf','model_path':model,'gpu':True,'profile':'rocm','context':65536,'context_mode':'manual','runtime':{'threads':4,'reasoning_budget':0},'fit_mode':'manual'});started=True
 deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state.get('error'))
  time.sleep(.25)
 else:raise TimeoutError('Model startup exceeded 45 seconds')
 gateway=TimeGateway(root,base,allow_deferred=True);found=runtime(root);port=free_port();token=secrets.token_urlsafe(32)
 arguments=argparse.ArgumentParser();arguments.add_argument('--candidate');options=arguments.parse_args()
 if options.candidate:
  candidate=Path(options.candidate).resolve()
  if not candidate.is_relative_to((root/'output/updates/harness-candidates/hermes').resolve()):raise ValueError('Probe candidate must belong to managed Hermes candidates')
  found={'python':candidate/'venv/Scripts/python.exe','venv':candidate/'venv','site':candidate/'venv/Lib/site-packages','source':candidate/'source'}
 command=[str(found['python']),'-I','-S',str(found['source']/'pm/_venv_entry.py'),str(found['site']),'-m','hermes_cli.main','dashboard','--host','127.0.0.1','--port',str(port),'--no-open','--skip-build','--isolated']
 harness=AgentHarness(folder,kind='hermes',port=port,binary=str(found['python']),command=command,base_url=gateway.url+'/v1',model_context=65536,model_output=512,mcp_servers={})
 original_environment=harness.environment
 def environment():
  env=original_environment();env.update(VIRTUAL_ENV=str(found['venv']),HERMES_WEB_DIST=str(found['source']/'hermes_cli/web_dist'),HERMES_DASHBOARD_SESSION_TOKEN=token);return env
 harness.environment=environment;harness.start()
 native_base=f'http://127.0.0.1:{port}'
 request=urllib.request.Request(native_base+'/api/mcp/servers',headers={'Authorization':'Bearer '+token})
 with urllib.request.urlopen(request,timeout=10) as response:servers=json.load(response)
 report['configured_mcp_servers']=[row.get('name') for row in servers.get('servers',[])]
 request=urllib.request.Request(native_base+'/api/mcp/servers/stargatelab/test',data=b'{}',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Origin':native_base})
 with urllib.request.urlopen(request,timeout=15) as response:report['mcp_probe']=json.load(response)
 if not report['mcp_probe'].get('ok'):raise RuntimeError('Native MCP connection failed: '+str(report['mcp_probe'].get('error')))
 asyncio.run(native_turn(token))
except Exception as error:report['error']=str(error)
finally:
 if harness:
  report['harness_closed']=harness.close()
  if not report['harness_closed']:harness._stop_child();report['passed']=False
 if gateway:gateway.close()
 if started:
  for attempt in range(20):
   try:call('/inference-backends/stop',{});break
   except urllib.error.HTTPError as error:
    if error.code!=409:raise
    time.sleep(.5)
 report['final_backend_state']=call('/inference-backends')['status'];report['passed']=report['passed'] and report['final_backend_state']=='idle'
 (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in report.items() if key in ('passed','scope','error','gateway_errors','final_backend_state')}));raise SystemExit(0 if report['passed'] else 1)
