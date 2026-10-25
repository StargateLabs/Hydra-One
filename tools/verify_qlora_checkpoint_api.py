import json,time,hashlib,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tools.verify_audio_update_cpu import call
root=Path.cwd();previous=json.loads((root/'output/verification/qlora-conversation-api-real.json').read_text(encoding='utf-8'))['state'];base=dict(previous['options'],model=previous['model'],train=previous['train_path'],validation=previous['validation_path'],save_steps=1,resume_checkpoint=None,steps=1);proof=dict(passed=False,scope='One native GPU QLoRA step, checkpoint integrity and resumed second step on local 135M; no quality claim')
def run(payload):
 checked=call('/local-training/preflight',payload)
 if not checked['ready']:raise RuntimeError(str(checked['reasons']))
 state=call('/local-training/start',payload);identity=state['output']
 try:
  deadline=time.monotonic()+180
  while time.monotonic()<deadline:
   state=call('/local-training')
   if state.get('output')!=identity:raise RuntimeError('Session changed')
   if state['status']!='running':break
   time.sleep(1)
  else:raise TimeoutError('Training deadline')
  if state['status']!='complete':raise RuntimeError('Training failed: '+str(state.get('workflow',{}).get('error'))+'; log '+state['log'])
  return state
 finally:
  state=call('/local-training')
  if state.get('output')==identity and state['status']=='running':call('/local-training/stop',{})
try:
 first=run(base);proof['first']=first;checkpoint=Path(first['workflow']['checkpoint']);before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in checkpoint.iterdir() if p.is_file()}
 resumed=run(dict(base,steps=2,resume_checkpoint=str(checkpoint)));proof['resumed']=resumed
 after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in checkpoint.iterdir() if p.is_file()}
 w=resumed['workflow'];assert w['resumed_from']==str(checkpoint) and w['completed_steps']==2 and any(row['step']==2 for row in w['loss_history']);assert before==after;assert w['export_greedy_tokens_equal']
 proof.update(passed=True,source_checkpoint_unchanged=True,checkpoint_integrity_verified=True,resumed_step=2)
except Exception as error:proof['error']=str(error);raise
finally:(root/'output/verification/qlora-checkpoint-resume-api-real.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
print('Native QLoRA checkpoint, optimizer resume, second step and adapter reload passed')
