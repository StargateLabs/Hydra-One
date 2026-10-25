"""Bounded native route discovery with invalid payloads, no model execution."""
import sys,time,urllib.error,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.agent_harness import AgentHarness
from serve.harness_updates import selected
from tools.harness_time_probe import TimeGateway,free_port,native_call
root=Path.cwd();gateway=TimeGateway(root,'http://127.0.0.1:8090');active=selected(root,'opencode')
harness=AgentHarness(root/'output/verification/open-plans-20261012/opencode-native-time',kind='opencode',port=free_port(),binary=active['binary'] if active else None,base_url=gateway.url+'/v1',mcp_servers={})
try:
 harness.start();time.sleep(2);sid=native_call(harness,'/api/session',{})['data']['id']
 for path in ('/api/session/'+sid+'/prompt','/api/session/'+sid+'/prompt_async','/api/session/'+sid+'/message','/api/session/'+sid+'/messages','/api/session/'+sid+'/turn','/api/session/'+sid+'/turns'):
  try:print(path,json.dumps(native_call(harness,path,{'parts':None},timeout=2))[:1000])
  except urllib.error.HTTPError as error:print(path,error.code,error.read(1500).decode())
  except Exception as error:print(path,str(error))
finally:harness.close();gateway.close()
