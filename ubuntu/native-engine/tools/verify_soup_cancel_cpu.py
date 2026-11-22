import json,time,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088'
def call(path,body=None):
 r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(r,timeout=20) as response:return json.load(response)
previous=call('/local-training');assert previous['runner']=='soup_cpu' and previous['status']=='complete';assert 'soup_cpu' in previous['runners']
payload={'runner':'soup_cpu','model':str(root/'output/verification/safetensors-cpu-fixture'),'train':str(root/'output/verification/training-smoke-train.jsonl'),'validation':str(root/'output/verification/training-smoke-validation.jsonl'),'steps':1000,'length':64}
started=call('/local-training/start',payload);assert started['status']=='running';time.sleep(.3);call('/local-training/stop',{})
for _ in range(30):
 state=call('/local-training')
 if state['status']!='running':break
 time.sleep(.2)
assert state['status']=='cancelled';assert not (root/'data/.gpu-campaign.lock').exists();assert state.get('workflow',{}).get('export_logits_verified') is not True
(root/'output/verification/soup-training-cancel-cpu.json').write_text(json.dumps({'restored_completed_session':True,'cancelled':state,'reservation_released':True},indent=2));print('Soup result recovered after restart; owned CPU job cancelled and reservation released')
