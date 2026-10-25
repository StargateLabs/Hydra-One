import base64,io,json,time,urllib.request
from pathlib import Path
from PIL import Image
root=Path.cwd();base='http://127.0.0.1:8088';proof=json.loads((root/'output/verification/vision-model-provenance.json').read_text(encoding='utf-8'));model,projector=[row['path'] for row in proof['files']];report={'scope':'Actual CPU image inference on a small control model, not general vision quality'}
def request(path,body=None):
 req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json','Origin':base})
 try:
  with urllib.request.urlopen(req,timeout=120) as response:return json.load(response)
 except urllib.error.HTTPError as error:raise RuntimeError(error.read().decode()) from error
assert request('/inference-backends')['status']=='idle'
try:
 report['start']=request('/inference-backends/start',{'mode':'gguf','model_path':model,'vision':True,'mmproj_path':projector,'gpu':False,'context':4096,'profile':'balanced','runtime':{'threads':2,'threads_batch':2,'batch':128,'micro_batch':128}})
 for _ in range(120):
  state=request('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.5)
 else:raise RuntimeError('Vision startup deadline')
 assert state['capabilities']['images'] is True,state
 image=Image.new('RGB',(128,128),(240,20,20));buffer=io.BytesIO();image.save(buffer,format='PNG');(root/'output/verification/vision-red-control.png').write_bytes(buffer.getvalue())
 report['reply']=request('/v1/chat/completions',{'model':state['public_model'],'messages':[{'role':'user','content':[{'type':'text','text':'What is the main color of this image? Answer briefly.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}}]}],'max_tokens':32,'stream':False,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}})
 answer=report['reply']['choices'][0]['message']['content'];report['basic_color_check']='red' in answer.lower();assert answer;report['passed']=True
finally:
 request('/inference-backends/stop',{})
 (root/'output/verification/vision-api-cpu.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'answer':answer,'basic_color_check':report['basic_color_check'],'passed':report['passed']}))

