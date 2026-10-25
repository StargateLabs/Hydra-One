import urllib.request,json,time
from pathlib import Path
base='http://127.0.0.1:8088'
def request(path,body):
 r=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
 with urllib.request.urlopen(r,timeout=120) as response:return json.load(response)
model=str(Path('output/verification/smollm2-export-f16.gguf').resolve());report={}
try:
 report['start']=request('/inference-backends/start',{'mode':'gguf','model_path':model,'gpu':False,'context':1024,'context_mode':'manual','runtime':{'threads':2,'threads_batch':2}})
 for _ in range(60):
  with urllib.request.urlopen(base+'/inference-backends') as response:state=json.load(response)
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(str(state))
  time.sleep(1)
 else:raise RuntimeError('Loading timeout')
 report['reply']=request('/v1/chat/completions',{'model':state['public_model'],'messages':[{'role':'user','content':'Say hello in one short sentence.'}],'max_tokens':16,'stream':False})
 assert report['reply']['choices'][0]['message']['content']
finally:report['stop']=request('/inference-backends/stop',{})
Path('output/verification/gguf-export-runtime-cpu.json').write_text(json.dumps(report,indent=2));print('Converted GGUF CPU loaded, replied and stopped')
