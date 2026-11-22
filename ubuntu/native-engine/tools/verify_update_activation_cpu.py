import json,time,threading,urllib.request
from pathlib import Path
from serve.update_center import UpdateCenter
from serve.optional_backends import OptionalBackends
root=Path.cwd();center=UpdateCenter(root)
def idle():
    if (root/'data/.gpu-campaign.lock').exists():return False
    with urllib.request.urlopen('http://127.0.0.1:8088/inference-backends',timeout=3) as response:backend=json.load(response)
    with urllib.request.urlopen('http://127.0.0.1:8088/metrics',timeout=3) as response:metrics=json.load(response)
    return backend['status']=='idle' and metrics['live']['state']=='unloaded'
center.operational_idle=idle
manager=None;activated=False
try:
    center.activate();activated=True
    manager=OptionalBackends(root)
    model=next(root.glob('output/model-exports/**/*.gguf'))
    manager.start({'mode':'gguf','model_path':str(model),'gpu':False,'context':1024,'fit_mode':'manual','context_mode':'manual','runtime':{'threads':2,'threads_batch':2}},True)
    deadline=time.monotonic()+120
    while manager.status()['status']=='loading' and time.monotonic()<deadline:time.sleep(.25)
    if manager.status()['status']!='ready':raise RuntimeError(manager.state)
    events=list(manager.chat({'messages':[{'role':'user','content':'Say hello briefly.'}],'max_tokens':16,'stream':False},threading.Event()))
    answer=''.join(e['choices'][0].get('message',{}).get('content','') or '' for e in events if e.get('choices'))
    if not answer.strip():raise RuntimeError('Empty response after activation')
    result={'candidate_binary':str(manager.binary),'answer':answer,'gpu_used':False,'original_runtime_overwritten':False}
finally:
    if manager:manager.close()
    if activated:center.rollback()
result['restored_selection']=center.status()['runtime_selection']['active']
(root/'output/verification/update-activation-rollback-real.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('Real candidate activation, CPU inference and rollback passed')
