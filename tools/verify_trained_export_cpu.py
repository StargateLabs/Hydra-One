"""Real adapter and merged export lifecycle, CPU fixture only."""
import json,time
from tools.verify_native_fit_cpu import call,ROOT

def main():
    directory=ROOT/'output/verification/lora-training-smoke-20261010-b'
    training=json.loads((directory/'workflow.json').read_text())
    if training['status']!='complete' or not training['export_logits_verified']:raise RuntimeError('Training/export unverified')
    if call('/metrics')['live']['state']!='unloaded' or call('/inference-backends')['status']!='idle':raise RuntimeError('Engines busy')
    results=[]
    for mode,model,adapter in [('adapter',training['base'],training['adapter']),('merged',training['merged'],None)]:
        try:
            call('/inference-backends/start',dict(mode='safetensors',model_path=model,adapter_path=adapter,gpu=False,context=1024,runtime={'threads':2}))
            deadline=time.monotonic()+60
            while True:
                status=call('/inference-backends')
                if status['status']=='ready':break
                if status['status']=='error':raise RuntimeError(status['error'])
                if time.monotonic()>deadline:raise RuntimeError('Readiness timeout')
                time.sleep(.5)
            response=call('/v1/chat/completions',dict(model=status['public_model'],messages=[dict(role='user',content='hello world')],max_tokens=8,temperature=0))
            if not response['choices'][0]['message']['content'].strip():raise RuntimeError('Empty response')
            results.append(dict(mode=mode,device=status['device_requested'],response=response))
        finally:
            state=call('/inference-backends')
            if state.get('model_path')==model and not state.get('busy'):call('/inference-backends/stop',{})
    report=dict(passed=True,scope='Trained random fixture lifecycle on CPU, no model quality/performance claim',runs=results)
    (ROOT/'output/verification/trained-export-api-cpu.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=True,adapter=True,merged=True,device='CPU')))

if __name__=='__main__':main()
