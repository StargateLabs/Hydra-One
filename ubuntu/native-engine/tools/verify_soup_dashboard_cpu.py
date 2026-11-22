import json,time,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088'
def call(path,body=None):
 r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(r,timeout=120) as response:return json.load(response)
assert call('/inference-backends')['status']=='idle'
model=json.loads((root/'output/verification/safetensors-trained-cpu-real-20261010.json').read_text())['model']['path']
payload={'runner':'soup_cpu','model':model,'train':str(root/'output/verification/training-smoke-train.jsonl'),'validation':str(root/'output/verification/training-smoke-validation.jsonl'),'steps':2,'length':64,'rank':4,'alpha':8,'learning_rate':0.0002,'accumulation':2,'seed':9,'checkpointing':True}
preflight=call('/local-training/preflight',payload);assert preflight['ready'] and preflight['soup']['cpu_training_enabled']
print(call('/local-training/start',payload)['runner'],flush=True)
for _ in range(180):
 training=call('/local-training')
 if training['status']!='running':break
 time.sleep(1)
else:call('/local-training/stop',{});raise RuntimeError('CPU training deadline')
(root/'output/verification/soup-training-dashboard-api.json').write_text(json.dumps(training,indent=2))
assert training['status']=='complete',training
assert training['workflow']['options']['runner']=='soup_cpu' and training['workflow']['export_logits_verified']
export=training['workflow']['merged'];report={'scope':'Actual Soup SFT CPU via dashboard; no GPU or performance claim','training':training}
try:
 call('/inference-backends/start',{'mode':'safetensors','model_path':export,'gpu':False,'context':1024,'context_mode':'manual','runtime':{'threads':2}})
 for _ in range(90):
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(str(state))
  time.sleep(1)
 else:raise RuntimeError('CPU reload deadline')
 report['response']=call('/v1/chat/completions',{'model':state['public_model'],'messages':[{'role':'user','content':'Say hello in one short sentence.'}],'max_tokens':16})
 assert report['response']['choices'][0]['message']['content'].strip()
finally:report['stop']=call('/inference-backends/stop',{})
(root/'output/verification/soup-export-api-cpu.json').write_text(json.dumps(report,indent=2));print('Soup dashboard CPU training, adapter, merged export, reload and response passed')
