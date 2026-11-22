import json,time,urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8088'
def call(path,body=None,base=BASE):
 with urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}),timeout=90) as r:return json.load(r)
path=r'C:\Users\Stargate\.cache\huggingface\hub\models--InfinimindCreations--Spark-X2.5-4B-uncensored-GGUF\snapshots\2f1d29be99469390b6fe7076ffb2e8b219169d41\Spark-X2.5-4B-uncensored-BF16.gguf'
assert call('/inference-backends')['status']=='idle'
plan=call('/inference-backends/context-plan',dict(model_path=path,gpu=True));print('Plan:',plan['recommended_context'],'model maximum:',plan['model_max_context'],flush=True)
started=False
try:
 state=call('/inference-backends/start',dict(mode='gguf',model_path=path,gpu=True,profile='rocm',context_mode='auto',fit_mode='auto',runtime=dict(batch=128,micro_batch=128,threads=8,threads_batch=16,flash_attention='auto'),inference_profile=dict(temperature=0,top_p=.95,max_tokens=512,thinking='none',web=True,tools=['strata_diagnostics__weather_forecast'])))
 started=True
 for _ in range(120):
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.5)
 assert state['status']=='ready',state
 props=call('/props',base='http://127.0.0.1:8091')
 generated=call('/v1/chat/completions',dict(model=state['public_model'],messages=[{'role':'user','content':'Rispondi solo con la parola OK.'}],max_tokens=32,stream=False,temperature=0,chat_template_kwargs={'enable_thinking':False}))
 assert generated['usage']['completion_tokens']>0,generated
 response=call('/v1/chat/completions',dict(model=state['public_model'],messages=[{'role':'system','content':'Usa weather_forecast per una previsione reale. Rispondi in italiano con città, data, temperature e fonte.'},{'role':'user','content':'Che tempo fa domani a Vercelli, Italia?'}],max_tokens=512,stream=False,temperature=0,strata_mcp=True,strata_web=True,chat_template_kwargs={'enable_thinking':False}))
 report=dict(plan=plan,context=state['context'],maximum=state['model_max_context'],runtime=state['runtime'],props=props,generation=generated,process_resources=state.get('process_resources'),answer=response['choices'][0]['message'])
 Path('output/verification/spark-auto-context-tools-real-20261010.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('Loaded context:',state['context'],'weather result:',any(e.get('event')=='result' and e.get('ok') for e in report['answer'].get('strata_mcp',[])),flush=True)
finally:
 state=call('/inference-backends')
 if started and state.get('model')=='Spark-X2.5-4B-uncensored-BF16' and not state.get('busy'):call('/inference-backends/stop',{})
