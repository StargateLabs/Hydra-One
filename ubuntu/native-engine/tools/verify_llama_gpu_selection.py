import sys,json,time,threading,concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.update_center import UpdateCenter
from serve.optional_backends import OptionalBackends
from serve.llama_gpu_update import selected_binary
from tools.verify_audio_update_cpu import call
root=Path.cwd();center=UpdateCenter(root)
center.operational_idle=lambda:call('/inference-backends')['status']=='idle' and call('/metrics')['live']['state']=='unloaded' and not (root/'data/.gpu-campaign.lock').exists()
# Load the currently prepared official GPU candidate; no file replacement.
assert center.job['component']=='llama.cpp'
cpu=root/'data/runtime-selection.json';cpu_before=cpu.read_bytes() if cpu.exists() else None
selected=center.activate_llama_gpu();binary=selected_binary(root)
model=json.loads((root/'output/verification/llama-b11541-cpu-real.json').read_text())['validated']['result']['validation']['model']
manager=OptionalBackends(root,discover_models=False);events=None
try:
 manager.start({'mode':'gguf','model_path':model,'gpu':True,'context':1024,'context_mode':'manual','fit_mode':'manual','runtime':{'threads':2,'threads_batch':2}},True)
 deadline=time.monotonic()+60
 while time.monotonic()<deadline:
  state=manager.status(include_models=False)
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.25)
 else:raise TimeoutError('Selected GPU load deadline')
 assert manager.binary==binary
 pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
 events=pool.submit(lambda:list(manager.chat({'messages':[{'role':'user','content':'Say hello briefly.'}],'max_tokens':16,'stream':False},threading.Event()))).result(timeout=30)
 assert any(e.get('choices',[{}])[0].get('message',{}).get('content') for e in events)
finally:
 manager.close()
 if 'pool' in locals():pool.shutdown(wait=False,cancel_futures=True)
 center.rollback_llama_gpu()
assert selected_binary(root) is None
assert (cpu.read_bytes() if cpu.exists() else None)==cpu_before
center.activate_llama_gpu()
assert selected_binary(root)==binary
proof=dict(passed=True,scope='Separate GPU selection, real small-model response, rollback and final selection; CPU selection unchanged; original installation preserved',binary=str(binary),response=events,cpu_selection_unchanged=True,rollback_to_original_verified=True,final_gpu_selected=True)
(root/'output/verification/llama-b11541-gpu-selection-real.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print('GPU selection: real response, rollback, CPU isolation and final selection passed')
