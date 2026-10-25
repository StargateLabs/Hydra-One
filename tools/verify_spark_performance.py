"""Bounded real Spark GGUF comparison using the selected local GPU runtime."""
import concurrent.futures,json,sys,threading,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.optional_backends import OptionalBackends
root=Path.cwd()
with urllib.request.urlopen('http://127.0.0.1:8090/inference-backends',timeout=20) as response:current=json.load(response)
if current['status']!='idle' or current.get('busy'):raise RuntimeError('Operational backend is busy')
model=next(row for row in current['local_models'] if row['name']=='Spark-X2.5-4B-Q8_0')
report={'model':model['name'],'path':model['path'],'passed':False,'scope':'Same Spark model/prompt/runtime; short warmup and two measured samples per setting; no long-term stability claim','variants':[]}
try:
 for goal in ('context','speed'):
  manager=OptionalBackends(root,discover_models=False)
  variant={'fit_goal':goal};report['variants'].append(variant)
  try:
   payload={'mode':'gguf','model_path':model['path'],'gpu':True,'context':4096,'context_mode':'auto','fit_mode':'auto','fit_goal':goal,'runtime':{'slots':1,'vram_percent':85}}
   fit=manager.fit_model(payload);variant['recommended']=fit['recommended'];manager.start(payload,True)
   deadline=time.monotonic()+90
   while time.monotonic()<deadline:
    state=manager.status(include_models=False)
    if state['status']=='error':raise RuntimeError(state['error'])
    if state['status']=='ready':break
    time.sleep(.2)
   else:raise TimeoutError('Spark load timeout')
   variant['actual']={key:state.get(key) for key in ['context','gpu_requested','runtime','backend','context_source']};variant['binary']=str(manager.binary);variant['samples']=[]
   with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    for index in range(3):
     start=time.monotonic();events=pool.submit(lambda:list(manager.chat({'messages':[{'role':'user','content':'Rispondi in italiano: spiega in due frasi a cosa serve una GPU.'}],'max_tokens':64,'temperature':0,'seed':42,'stream':False,'cache_prompt':False,'chat_template_kwargs':{'enable_thinking':False}},threading.Event()))).result(timeout=40)
     event=next(event for event in reversed(events) if event.get('choices'))
     variant['samples'].append({'warmup':index==0,'elapsed_s':time.monotonic()-start,'usage':event.get('usage'),'timings':event.get('timings'),'text':event['choices'][0]['message'].get('content'),'reasoning':event['choices'][0]['message'].get('reasoning_content')})
   variant['startup_log']=(root/'output/verification/optional-backend-server.log').read_text(encoding='utf-8',errors='replace')[-20000:]
  finally:manager.close()
 report['passed']=all(all(sample['usage']['completion_tokens']>0 for sample in variant['samples']) for variant in report['variants'])
 assert report['passed']
 print(json.dumps({'passed':report['passed'],'model':report['model'],'variants':[{'goal':v['fit_goal'],'context':v['actual']['context'],'gpu':v['actual']['gpu_requested'],'decode_tps':[s['timings'].get('predicted_per_second') for s in v['samples'] if not s['warmup']],'prefill_tps':[s['timings'].get('prompt_per_second') for s in v['samples'] if not s['warmup']]} for v in report['variants']]},ensure_ascii=False))
finally:(root/'output/verification/spark-unsloth-performance-real.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
