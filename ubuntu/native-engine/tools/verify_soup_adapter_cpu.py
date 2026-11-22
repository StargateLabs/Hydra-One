import json,time,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088'
def call(path,body=None):
 r=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(r,timeout=120) as response:return json.load(response)
training=json.loads((root/'output/verification/soup-training-dashboard-api.json').read_text());w=training['workflow'];report={}
try:
 call('/inference-backends/start',{'mode':'safetensors','model_path':training['model'],'adapter_path':w['adapter'],'gpu':False,'context':1024,'context_mode':'manual','runtime':{'threads':2}})
 for _ in range(90):
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(str(state))
  time.sleep(1)
 else:raise RuntimeError('CPU readiness deadline')
 report['response']=call('/v1/chat/completions',{'model':state['public_model'],'messages':[{'role':'user','content':'Say hello in one short sentence.'}],'max_tokens':16})
 assert report['response']['choices'][0]['message']['content'].strip()
finally:report['stop']=call('/inference-backends/stop',{})
(root/'output/verification/soup-adapter-api-cpu.json').write_text(json.dumps(report,indent=2));print('Soup adapter loaded, replied and stopped through original runtime')
