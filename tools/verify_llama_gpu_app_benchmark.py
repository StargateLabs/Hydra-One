import sys,json,time,psutil
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tools.verify_audio_update_cpu import call
root=Path.cwd();d=json.loads((root/'output/verification/llama-b11541-cpu-real.json').read_text());model=d['validated']['result']['validation']['model'];expected=(root/'output/updates/candidates/524fc4c89c5145f6b7ad034bd7eaf1fe/llama-server.exe').resolve()
assert call('/inference-backends')['status']=='idle' and call('/metrics')['live']['state']=='unloaded'
started=False;proof={'passed':False,'scope':'Real app-selected b11541 GPU, small-model benchmark; not 125B performance'}
try:
 call('/inference-backends/start',{'mode':'gguf','model_path':model,'gpu':True,'context':1024,'fit_mode':'manual','context_mode':'manual','runtime':{'threads':2,'threads_batch':2}});started=True
 deadline=time.monotonic()+60
 while time.monotonic()<deadline:
  state=call('/inference-backends')
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.25)
 else:raise TimeoutError('App GPU load deadline')
 connections=[c for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==8091 and c.status=='LISTEN'];assert len(connections)==1
 actual=Path(psutil.Process(connections[0].pid).exe()).resolve();assert actual==expected
 job=call('/benchmark-lab/start',{'model':'optional_active','runs':3,'tokens':32,'quality':False});identity=job['id'];deadline=time.monotonic()+60
 while time.monotonic()<deadline:
  job=call('/benchmark-lab')['job']
  if job.get('id')==identity and job['status'] not in ('running','queued','cancelling'):break
  time.sleep(.25)
 else:
  call('/benchmark-lab/stop',{});raise TimeoutError('App benchmark deadline')
 assert job['status']=='complete' and job['completed_samples']==4
 proof.update(passed=True,actual_executable=str(actual),job=job)
finally:
 if started:call('/inference-backends/stop',{})
 proof['final_backend_status']=call('/inference-backends')['status'];(root/'output/verification/llama-b11541-gpu-app-benchmark-real.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print('App starts actual b11541 GPU binary; warmup + three measured requests persisted; own model stopped')
