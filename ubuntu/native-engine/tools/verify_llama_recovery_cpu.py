"""Real CPU generation check using the installed Unsloth llama.cpp binary."""
import json,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from serve.optional_backends import OptionalBackends
manager=OptionalBackends(root)
path=next((Path.home()/'.cache/huggingface/hub/models--unsloth--Qwen3.5-4B-MTP-GGUF/snapshots').glob('*/Qwen3.5-4B-UD-Q4_K_XL.gguf'))
report={'model_path':str(path),'device':'cpu','context':4096}
try:
    manager.start(dict(mode='gguf',model_path=str(path),gpu=False,context=4096,profile='balanced'),True)
    deadline=time.monotonic()+180
    while manager.status()['status']=='loading':
        if time.monotonic()>deadline:raise RuntimeError('Loading deadline')
        time.sleep(.5)
    state=manager.status()
    if state['status']!='ready':raise RuntimeError(str(state.get('error')))
    started=time.monotonic()
    events=list(manager.client.chat([{'role':'user','content':'Rispondi solo con: Ciao'}], 'optional-model',32,chat_template_kwargs={'enable_thinking':False}))
    report.update(elapsed_s=time.monotonic()-started,response=events)
    assert events[0]['choices'][0]['message'].get('content'),events
    report['passed']=True
finally:
    manager.close()
    (root/'output/verification/llama-recovery-cpu.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
