import sys,json,socket
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.agent_harness import AgentHarness
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
h=AgentHarness(Path.cwd()/'output/verification/trueforge-probe',kind='trueforge',port=port,mcp_servers={},base_url='http://127.0.0.1:8088/v1')
try:
 h.start();print('TrueForge official UI ready and local provider configured');print(h.connect()['ui'])
finally:h.stop()
