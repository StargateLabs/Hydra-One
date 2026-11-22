import json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from tools.verify_audio_update_cpu import call
root=Path.cwd();proof=json.loads((root/'output/verification/soup-streaming-candidate-real.json').read_text());payload=dict(model=proof['workflow']['base'],train=str(root/'output/verification/training-smoke-train.jsonl'),validation=str(root/'output/verification/training-smoke-validation.jsonl'),runner='soup_native',device='cuda',steps=1,length=64,layer_streaming=True)
plan=call('/local-training/preflight',payload)
assert plan['ready'],plan['reasons']
state=call('/local-training/start',payload);deadline=time.monotonic()+45
while state['status']=='running' and time.monotonic()<deadline:time.sleep(.5);state=call('/local-training')
assert state['status']=='complete',state
assert state['workflow']['streaming_active'] and state['workflow']['export_greedy_tokens_equal']
report=dict(passed=True,scope='One real streaming GPU step started by dashboard API; adapter reloaded with matching logits/tokens; not large-model quality',state=state,plan=plan)
(root/'output/verification/soup-streaming-app-real.json').write_text(json.dumps(report,indent=2));print('Managed streaming training and adapter export passed')
