import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tools.verify_audio_update_cpu import call
root=Path.cwd();model=json.loads((root/'output/verification/unsloth-native-nf4-gpu-real.json').read_text())['model'];started=False;proof={'passed':False,'scope':'App Native Unsloth NF4 on local 135M model; eight-token answer and three short wall-rate samples, not 125B performance'}
try:
 assert call('/inference-backends')['status']=='idle' and call('/metrics')['live']['state']=='unloaded'
 call('/inference-backends/start',dict(mode='safetensors',model_path=model,gpu=True,context=1024,context_mode='manual',fit_mode='manual',runtime={'threads':2,'python_loader':'unsloth','python_quantization':'nf4'}));started=True
 deadline=time.monotonic()+75
 while time.monotonic()<deadline:
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.25)
 else:raise TimeoutError('NF4 loading deadline')
 assert state['native_loader']=='unsloth' and state['quantization']=='nf4'
 response=call('/v1/chat/completions',{'model':state['public_model'],'messages':[{'role':'user','content':'Say hello briefly.'}],'max_tokens':8,'stream':False,'temperature':0})
 assert response['choices'][0]['message']['content']
 job=call('/benchmark-lab/start',{'model':'optional_active','runs':3,'tokens':32,'quality':False});identity=job['id'];deadline=time.monotonic()+60
 while time.monotonic()<deadline:
  job=call('/benchmark-lab')['job']
  if job.get('id')==identity and job['status'] not in ('running','queued','cancelling'):break
  time.sleep(.25)
 else:
  call('/benchmark-lab/stop',{});raise TimeoutError('NF4 benchmark deadline')
 assert job['status']=='complete' and job['configuration']['runtime']['python_quantization']=='nf4'
 proof.update(passed=True,state=state,response=response,benchmark=job,memory_sample=call('/inference-backends').get('gpu_process_resources'))
finally:
 if started:call('/inference-backends/stop',{})
 proof['final_backend_status']=call('/inference-backends')['status'];(root/'output/verification/unsloth-nf4-app-benchmark-real.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print('NF4 app: actual quantization confirmed, usable reply, benchmark persisted and worker stopped')
