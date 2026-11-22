import json,sys,socket
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.agent_harness import AgentHarness
root=Path.cwd();folder=root/'output/verification/harness-native-real';folder.mkdir(parents=True,exist_ok=True)
for kind in ['opencode','dsh']:
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 harness=AgentHarness(folder/kind,kind=kind,port=port,mcp_servers={},base_url='http://127.0.0.1:8080/v1')
 try:
  harness.start();entry=harness.connect();(folder/(kind+'-entry.json')).write_text(json.dumps(entry))
  print(kind,'official UI ready',flush=True)
  import subprocess
  subprocess.run(['C:/Program Files/nodejs/node.exe','output/playwright/verify-harness-official-ui.cjs',kind,str(folder/(kind+'-entry.json'))],check=True,timeout=35)
 finally:harness.stop()
