import json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tools.verify_audio_update_cpu import call
root=Path.cwd();base=json.loads((root/'output/verification/unsloth-qlora-managed-api-real.json').read_text(encoding='utf-8'))['state']['model'];folder=root/'output/verification/qlora-conversation-datasets'
payload=dict(model=base,train=str(folder/'train.jsonl'),validation=str(folder/'validation.jsonl'),runner='unsloth_qlora',steps=1,length=128,rank=4,alpha=8,learning_rate=.0002,device='cuda')
preflight=call('/local-training/preflight',payload);assert preflight['ready'] and preflight['loss_scope']=='assistant_only'
state=call('/local-training/start',payload);output=state['output'];proof=dict(passed=False,scope='One real native GPU QLoRA conversation step on 135M; not general model quality')
try:
 deadline=time.monotonic()+180
 while time.monotonic()<deadline:
  state=call('/local-training')
  if state.get('output')!=output:raise RuntimeError('Session changed')
  if state['status']!='running':break
  time.sleep(1)
 else:raise TimeoutError('Training deadline exceeded')
 proof.update(state=state,passed=state['status']=='complete' and state.get('workflow',{}).get('loss_scope')=='assistant_only' and state.get('workflow',{}).get('export_greedy_tokens_equal') is True)
 print(json.dumps({'passed':proof['passed'],'status':state['status'],'error':state.get('workflow',{}).get('error')}))
finally:
 state=call('/local-training')
 if state.get('output')==output and state['status']=='running':call('/local-training/stop',{})
 (root/'output/verification/qlora-conversation-api-real.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
if not proof['passed']:raise RuntimeError('Conversational QLoRA verification failed')
