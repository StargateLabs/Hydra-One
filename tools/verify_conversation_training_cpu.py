import json,time,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088'
def request(path,body=None):
 r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(r,timeout=30) as response:return json.load(response)
model=next(m for m in request('/inference-backends')['local_models'] if m['format']=='Safetensors' and 'SmolLM2' in m['name'])['path']
folder=root/'output/verification/conversation-training';folder.mkdir(exist_ok=True)
for split,turns in [('train',[('Say hello in Italian.','Ciao!'),('Say thanks in Italian.','Grazie!')]),('validation',[('Say goodbye in Italian.','Arrivederci!')])]:
 (folder/(split+'.jsonl')).write_text(''.join(json.dumps({'messages':[{'role':'user','content':q},{'role':'assistant','content':a}]})+'\n' for q,a in turns),encoding='utf-8')
payload={'model':model,'train':str(folder/'train.jsonl'),'validation':str(folder/'validation.jsonl'),'runner':'trl_cpu','steps':2,'length':128,'rank':2,'alpha':4,'learning_rate':0.0002}
plan=request('/local-training/preflight',payload);assert plan['ready'],plan
request('/local-training/start',payload)
for _ in range(180):
 state=request('/local-training')
 if state['status']!='running':break
 time.sleep(1)
else:request('/local-training/stop',{});raise RuntimeError('Training deadline')
(folder/'api-result.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
assert state['status']=='complete',state
assert state['workflow']['loss_scope']=='assistant_only' and min(state['workflow']['supervised_tokens_per_row'])>0
assert state['workflow']['export_logits_verified']
print('Actual conversational CPU training complete, assistant-only loss and merged export verified')
