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
 for tool,prompt in [('read_system_state','Usa lo strumento per leggere lo stato del sistema e riassumilo.'),('read_prepared_models','Usa lo strumento per elencare i modelli preparati.'),('read_benchmark_results','Usa lo strumento per leggere gli ultimi benchmark.'),('search_web','Cerca sul web la documentazione ufficiale Open-Meteo e cita una fonte.'),('read_web_page','Leggi https://open-meteo.com/en/docs e riassumi brevemente la pagina.'),('weather_forecast','Che tempo fa domani a Vercelli, Italia? Dammi temperature, probabilità di pioggia, data e fonte.')]:
  request=dict(model=state['public_model'],messages=[{'role':'system','content':'Use the available tools to answer with current real data. For weather use weather_forecast. If the city is missing ask which city. Cite the source. Do not invent facts.'},{'role':'user','content':prompt}],max_tokens=1024,stream=False,temperature=0,strata_mcp=True,strata_web=True,chat_template_kwargs={'enable_thinking':False})
  response=call('/v1/chat/completions',request);message=response['choices'][0]['message'];events=message.get('strata_mcp',[])
  ok=any(e.get('event')=='call' and e.get('name','').endswith('__'+tool) for e in events) and any(e.get('event')=='result' and e.get('ok') for e in events)
  report['tests'].append(dict(tool=tool,passed=ok,events=events,answer=message.get('content'),usage=response['usage']))
  print(tool,'executed=',ok,flush=True)
 response=call('/v1/chat/completions',dict(model=state['public_model'],messages=[{'role':'system','content':'For weather use weather_forecast only when the city is given. Ask the city if missing. Never invent location.'},{'role':'user','content':'Che tempo fa domani?'}],stream=False,max_tokens=256,temperature=0,strata_mcp=True,strata_web=True,chat_template_kwargs={'enable_thinking':False}))
 report['missing_city']=response['choices'][0]['message']
 Path('output/verification/chat-all-tools-real-20261010.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Missing city:',report['missing_city'].get('content'),flush=True)
finally:
 state=call('/inference-backends')
 if state.get('model')=='MiniCPM5-2B-Q8_0' and not state.get('busy'):call('/inference-backends/stop',{})
