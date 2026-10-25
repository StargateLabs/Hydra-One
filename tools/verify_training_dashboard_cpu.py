import json,time,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088'
def request(path,body=None):
 r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(r,timeout=15) as response:return json.load(response)
payload={'model':str(root/'output/verification/safetensors-cpu-fixture'),'train':str(root/'output/verification/training-smoke-train.jsonl'),'validation':str(root/'output/verification/training-smoke-validation.jsonl'),'steps':2,'length':32,'rank':4,'alpha':8,'learning_rate':0.0002,'accumulation':2,'seed':9,'checkpointing':True}
preflight=request('/local-training/preflight',payload);assert preflight['ready'];print(request('/local-training/start',payload)['status'],flush=True)
for _ in range(120):
 state=request('/local-training')
 if state['status']!='running':break
 time.sleep(1)
else:request('/local-training/stop',{});raise RuntimeError('Training deadline exceeded')
(root/'output/verification/training-dashboard-api.json').write_text(json.dumps(state,indent=2))
assert state['workflow']['options']['rank']==4 and state['workflow']['options']['checkpointing'] is True
print(json.dumps(state,indent=2));assert state['status']=='complete' and state['workflow']['export_logits_verified']
