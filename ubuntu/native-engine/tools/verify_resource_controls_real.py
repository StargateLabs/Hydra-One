import json,time,urllib.request
from pathlib import Path
BASE='http://127.0.0.1:8088'
def call(path,body=None):
 with urllib.request.urlopen(urllib.request.Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'}),timeout=90) as r:return json.load(r)
model=r'C:\Users\Stargate\.cache\huggingface\hub\models--openbmb--MiniCPM5-2B-GGUF\snapshots\2079a22f3beaa4e306449978533478fe0522f4b3\MiniCPM5-2B-Q8_0.gguf'
assert call('/inference-backends')['status']=='idle'
started=False
try:
 call('/inference-backends/start',dict(mode='gguf',model_path=model,gpu=True,profile='rocm',fit_mode='manual',context_mode='manual',context=8192,runtime=dict(batch=128,micro_batch=64,threads=8,threads_batch=16,flash_attention='auto',kv_type='q8_0',slots=2,cache_ram_mib=512,checkpoints=4,vram_percent=75,load_mode='mmap',spec_type='none',reasoning_budget=0)))
 started=True
 for _ in range(120):
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.5)
 assert state['context']==8192 and state['context_per_slot']==4096,state
 response=call('/v1/chat/completions',dict(model=state['public_model'],messages=[{'role':'user','content':'Return only the number: 7 + 5 = ?'}],max_tokens=32,stream=False,temperature=0,chat_template_kwargs={'enable_thinking':False}))
 state=call('/inference-backends');assert state['process_resources']['rss_bytes']>0
 report=dict(configuration=state['runtime'],context=state['context'],context_per_slot=state['context_per_slot'],model_max_context=state['model_max_context'],process_resources=state['process_resources'],response=response,arithmetic_exact=response['choices'][0]['message'].get('content','').strip()=='12')
 Path('output/verification/resource-controls-real-20261010.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print('KV q8_0, 2 slots, context 8192, budget75, actual process RAM:',state['process_resources']['rss_bytes'],'answer:',response['choices'][0]['message'].get('content'),flush=True)
finally:
 state=call('/inference-backends')
 if started and state.get('model')=='MiniCPM5-2B-Q8_0' and not state.get('busy'):call('/inference-backends/stop',{})
