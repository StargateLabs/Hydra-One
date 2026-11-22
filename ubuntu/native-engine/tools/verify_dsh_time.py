"""One original DeepSeek Harness time-tool turn in an isolated native home."""
import http.cookiejar,json,sys,time,urllib.request,urllib.error,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.agent_harness import AgentHarness
from serve.harness_updates import selected
from tools.harness_time_probe import TimeGateway,free_port,dsh_final_text
root=Path(__file__).resolve().parents[1];base='http://127.0.0.1:8090'
folder=root/'output/verification/open-plans-20261012/dsh-native-time';folder.mkdir(parents=True,exist_ok=True)
def call(path,payload=None):
 request=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
report={'passed':False,'scope':'One original DeepSeek Harness time-tool turn; not all-model certification'}
harness=None;gateway=None;started=False
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
 gateway=TimeGateway(root,base);active=selected(root,'dsh')
 harness=AgentHarness(folder,kind='dsh',port=free_port(),binary=active['binary'] if active else None,base_url=gateway.url+'/v1',model_context=65536,model_output=512,mcp_servers={'stargatelab':{'url':gateway.url+'/harness/mcp'}})
 harness.start();time.sleep(2)
 opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 with opener.open(harness.status()['url'],timeout=10) as response:response.read()
 native_base=f'http://127.0.0.1:{harness.port}'
 def rpc(method,payload):
  body={'type':'client-request','rpcId':uuid.uuid4().hex,'method':method,'payload':{'args':{'request':payload}}}
  request=urllib.request.Request(native_base+'/api/'+method,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':native_base})
  with opener.open(request,timeout=10) as response:reply=json.load(response)
  if not reply['result']['ok']:raise RuntimeError(json.dumps(reply['result']['error']))
  return reply['result']['value']
 session=rpc('session/create',{'cwd':str(folder)})['sessionId'];report['session_id']=session
 report['prompt_accepted']=rpc('session/prompt',{'sessionId':session,'requestId':uuid.uuid4().hex,'mode':'queue','content':[{'type':'text','text':'Call the MCP tool time__get_current_time with timezone Europe/Rome and report the returned time in one sentence. Do not read or write files or run commands.'}]})
 deadline=time.monotonic()+75
 while time.monotonic()<deadline:
  projection=rpc('session/projections',{'sessionId':session});report['projection']=projection
  if gateway.errors:break
  if gateway.calls and not harness.status().get('busy'):break
  time.sleep(.5)
 report['tool_calls']=gateway.calls;report['gateway_errors']=gateway.errors;report['requests']=gateway.requests
 if report.get('projection'):
  report['native_page']=rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':report['projection']['asOfSeq'],'maxMessages':20})
 successful=[item for item in gateway.calls if 'result' in item['response'] and not item['response']['result'].get('isError') and item['response']['result'].get('content')]
 report['final_assistant_text']=dsh_final_text(report.get('native_page',{}))
 report['passed']=bool(successful) and bool(report['final_assistant_text']) and not gateway.errors and not harness.status().get('busy')
except urllib.error.HTTPError as error:report['error']=str(error)+': '+error.read(2000).decode(errors='replace')
except Exception as error:report['error']=str(error)
finally:
 if harness:
  report['harness_closed']=harness.close()
  if not report['harness_closed']:
   # This probe owns only its isolated child; a timed-out proof must not leak it.
   harness._stop_child()
   report['passed']=False
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
