"""Compare real single-file and multi-part GGUF on the existing CPU server."""
import json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_audio_update_cpu import call
from serve.gguf_parts import local_parts,weight_bytes
def run(model):
    ticket=None
    try:
        ticket=call('/inference-backends/start',{'mode':'gguf','model_path':str(model),'gpu':False,'context':1024,'context_mode':'manual','runtime':{'threads':2,'threads_batch':2}})
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            state=call('/inference-backends')
            if state['status']=='ready':break
            if state['status']=='error':raise RuntimeError(state['error'])
            time.sleep(.25)
        else:raise TimeoutError('CPU model loading timeout')
        response=call('/v1/chat/completions',{'model':state['public_model'],'messages':[{'role':'user','content':'Say hello in one short sentence.'}],'temperature':0,'max_tokens':16,'stream':False})
        assert response['choices'][0]['message']['content'].strip()
        return {'state':state,'response':response}
    finally:
        state=call('/inference-backends')
        if ticket and state.get('model_path')==str(model) and state.get('started_at')==ticket.get('started_at') and not state.get('busy'):call('/inference-backends/stop',{})
def main():
    assert call('/metrics')['live']['state']=='unloaded' and call('/inference-backends')['status']=='idle'
    first=next((ROOT/'output/model-exports/split-smollm2-20261010').glob('*-00001-of-*.gguf'))
    parts=local_parts(first);assert len(parts)>1
    control=run(ROOT/'output/verification/smollm2-export-f16.gguf');candidate=run(first)
    equal=control['response']['choices'][0]['message']['content']==candidate['response']['choices'][0]['message']['content']
    assert equal,'Single and multipart greedy responses differ'
    report={'scope':'Actual SmolLM2-135M CPU single vs multipart GGUF, one 16-token greedy probe; not general quality or GPU performance','parts':[str(path) for path in parts],'total_bytes':weight_bytes(first),'greedy_response_equal':equal,'control':control,'candidate':candidate,'gpu_used':False}
    (ROOT/'output/verification/gguf-parts-cpu-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Real multipart GGUF loaded on CPU; greedy response matches single file')
if __name__=='__main__':main()
