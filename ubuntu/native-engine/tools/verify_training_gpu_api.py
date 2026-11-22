import json,time
from pathlib import Path
from urllib.request import Request,urlopen
root=Path(__file__).resolve().parents[1]
def call(path,body=None):
 with urlopen(Request('http://127.0.0.1:8088'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}),timeout=30) as r:return json.load(r)
c=json.loads((root/'output/verification/training-gpu-command.json').read_text(encoding='utf-8'))
payload=dict(model=c['model'],train=c['folder']+'/train.jsonl',validation=c['folder']+'/validation.jsonl',steps=2,length=32,device='cuda')
print(call('/local-training/preflight',payload)['ready'],flush=True)
call('/local-training/start',payload)
try:
 deadline=time.monotonic()+120
 while time.monotonic()<deadline:
  state=call('/local-training')
  if state['status']!='running':break
  time.sleep(.5)
 else:raise RuntimeError('Training deadline exceeded')
 assert state['status']=='complete' and state['device']=='cuda' and state['workflow']['export_logits_verified'],state
 (root/'output/verification/training-gpu-api-real.json').write_text(json.dumps(dict(passed=True,state=state),indent=2),encoding='utf-8')
 print('GPU training API, adapter and export verified')
finally:
 if call('/local-training')['status']=='running':call('/local-training/stop',{})
