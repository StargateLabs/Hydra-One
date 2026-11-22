import json,time,urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8088'
def call(path,body=None):
 data=json.dumps(body).encode() if body is not None else None
 with urllib.request.urlopen(urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'}),timeout=180) as r:return json.load(r)
model=r'C:\Users\Stargate\.cache\huggingface\hub\models--openbmb--MiniCPM5-2B-GGUF\snapshots\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf'
assert call('/metrics')['live']['state']=='unloaded'
assert call('/inference-backends')['status']=='idle'
try:
 call('/inference-backends/start',dict(mode='gguf',model_path=model,gpu=True,profile='rocm'))
 for i in range(180):
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(1)
 else:raise RuntimeError('Loading timed out')
 report={'model':state['public_model'],'tests':[]}
 for tool,args,prompt in [('read_system_state',{},'Read the current system state with the specified tool, then briefly state the model name.'),('read_web_page',{'url':'https://huggingface.co/docs/hub/api'},'Read https://huggingface.co/docs/hub/api with the specified tool. Briefly summarize the page and cite its URL.')]:
  request=dict(model=state['public_model'],messages=[{'role':'user','content':prompt}],max_tokens=512,stream=False,temperature=0,strata_mcp=True,strata_web=True,chat_template_kwargs={'enable_thinking':False},tool_choice={'type':'function','function':{'name':'strata_diagnostics__'+tool}})
  response=call('/v1/chat/completions',request);message=response['choices'][0]['message'];events=message.get('strata_mcp',[])
  report['tests'].append(dict(tool=tool,events=events,answer=message.get('content'),usage=response['usage']))
  print(tool,'executed=',any(e.get('event')=='result' and e.get('ok') for e in events),flush=True)
 call('/benchmark-lab/start',dict(model='optional_active',tokens=128,runs=3,quality=True))
 for i in range(120):
  lab=call('/benchmark-lab');job=lab['job']
  if job['status'] not in ('running','cancelling'):break
  time.sleep(1)
 assert job['status']=='complete',job
 report['benchmark']=job
 report['records']=call('/benchmarks')['best_groups']
 Path('output/verification/optional-integrated-real-20261010.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('benchmark=',job['status'],'records=',len(report['records']),flush=True)
finally:
 state=call('/inference-backends')
 if state.get('model')=='MiniCPM5-2B-Q8_0' and not state.get('busy'):call('/inference-backends/stop',{})
