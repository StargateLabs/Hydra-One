"""One native OpenCode read-only MCP turn; preserves user homes and model state."""
import json,sys,time,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.agent_harness import AgentHarness
from serve.harness_updates import selected
from tools.harness_time_probe import TimeGateway,free_port,native_call,opencode_final_text
root=Path(__file__).resolve().parents[1];base='http://127.0.0.1:8090'
folder=root/'output/verification/open-plans-20261012/opencode-native-time';folder.mkdir(parents=True,exist_ok=True)
def call(path,payload=None):
 request=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
report={'passed':False,'scope':'One original OpenCode time-tool turn, isolated home, local Qwen3.5-4B; no universal certification'}
harness=None;gateway=None;started=False
try:
 assert call('/metrics')['live']['state']=='unloaded' and call('/inference-backends')['status']=='idle','Existing model active'
 rows=json.loads((folder.parent/'model-compatibility-matrix.json').read_text(encoding='utf-8'))['models']
 model=next(row['path'] for row in rows if row['name']=='Qwen3.5-4B-UD-Q4_K_XL')
 call('/inference-backends/start',{'mode':'gguf','model_path':model,'gpu':True,'profile':'rocm','context':65536,'context_mode':'manual','runtime':{'threads':4,'reasoning_budget':0},'fit_mode':'manual'});started=True
 deadline=time.monotonic()+45
 while time.monotonic()<deadline:
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state.get('error'))
  time.sleep(.25)
 else:raise TimeoutError('Model startup exceeded 45 seconds')
 gateway=TimeGateway(root,base,allow_code_mode=True);active=selected(root,'opencode')
 harness=AgentHarness(folder,kind='opencode',port=free_port(),binary=active['binary'] if active else None,base_url=gateway.url+'/v1',model_context=65536,model_output=512,mcp_servers={'stargatelab':{'url':gateway.url+'/harness/mcp'}})
 harness.start();time.sleep(2)
 session=native_call(harness,'/api/session',{})['data']['id']
 reply=native_call(harness,'/api/session/'+session+'/prompt',{'text':'Use the execute tool with this exact JavaScript code: return await tools.stargatelab.time__get_current_time({timezone:"Europe/Rome"}); Then report the returned time in one sentence. Do not import modules, fetch URLs, read, edit or write files.'},timeout=85)
 report['native_response']=reply
 deadline=time.monotonic()+75
 while time.monotonic()<deadline:
  active_sessions=native_call(harness,'/api/session/active')
  session_state=native_call(harness,'/api/session/'+session)['data']
  if session_state.get('outcome') in ('succeeded','failed') and not active_sessions.get('data'):break
  if gateway.errors:break
  time.sleep(.5)
 report['session']=native_call(harness,'/api/session/'+session)
 report['tool_calls']=gateway.calls;report['gateway_errors']=gateway.errors;report['requests']=gateway.requests
 successful_calls=[item for item in gateway.calls if 'result' in item['response'] and not item['response']['result'].get('isError') and item['response']['result'].get('content')]
 report['successful_tool_results']=len(successful_calls)
 report['passed']=bool(successful_calls) and not gateway.errors and not active_sessions.get('data') and report['session']['data'].get('outcome')=='succeeded'
except urllib.error.HTTPError as error:report['error']=str(error)+': '+error.read(2000).decode('utf-8',errors='replace')
except Exception as error:report['error']=str(error)
finally:
 if harness:harness.close()
 if report.get('session'):
  report['final_assistant_text']=opencode_final_text(folder,report['session']['data']['id'])
  report['passed']=report['passed'] and bool(report['final_assistant_text'])
 if gateway:gateway.close()
 if started:
  for attempt in range(20):
   try:call('/inference-backends/stop',{});break
   except urllib.error.HTTPError as error:
    if error.code!=409:raise
    time.sleep(.5)
 report['final_backend_state']=call('/inference-backends')['status']
 report['passed']=report['passed'] and report['final_backend_state']=='idle'
 (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in report.items() if key in ('passed','scope','error','final_backend_state','successful_tool_results')}))
raise SystemExit(0 if report['passed'] else 1)
