"""Real CPU equivalence proof: uninterrupted training versus saved/resumed training."""
import json
from pathlib import Path
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]


def main():
    previous=json.loads((ROOT/'output/verification/open-plans-20261012/vlm-training-real.json').read_text())
    source=json.loads(Path(previous['report']).read_text())['options']
    runtime=ROOT/'data/trl-advanced-runtime/Scripts/python.exe'
    parent=ROOT/'output/training'/('verification-vlm-resume-'+uuid.uuid4().hex)
    parent.mkdir(parents=True)
    def run(name,steps,resume=None):
        output=parent/name
        command=[str(runtime),str(ROOT/'tools/train_vlm_lora.py'),'--model',source['model'],'--train',source['train'],
            '--validation',source['validation'],'--output',str(output),'--steps',str(steps),'--length','64','--save-steps','1','--checkpointing']
        if resume:command+=['--resume-checkpoint',str(resume)]
        with (parent/(name+'.log')).open('w',encoding='utf-8') as log:
            subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=180)
        return output
    uninterrupted=run('uninterrupted',4)
    initial=run('initial',2)
    resumed=run('resumed',4,initial/'trainer/checkpoint-2')
    comparison="""import sys,json,torch;from safetensors.torch import load_file;from pathlib import Path;a=load_file(str(Path(sys.argv[1])/'adapter_model.safetensors'));b=load_file(str(Path(sys.argv[2])/'adapter_model.safetensors'));differences={k:float((a[k]-b[k]).abs().max())for k in a};print(json.dumps({'maximum_difference':max(differences.values()),'tensors':len(a)}));assert all(torch.equal(a[k],b[k])for k in a),differences"""
    result=subprocess.run([str(runtime),'-c',comparison,str(uninterrupted/'adapter'),str(resumed/'adapter')],capture_output=True,text=True,check=True,timeout=30)
    proof={'fixture_only':True,'scope':'Tiny untrained LLaVA CPU: deterministic checkpoint equivalence; no image-quality claim',
           'outputs':str(parent),'comparison':json.loads(result.stdout),'steps':4,'checkpointing':True}
    (ROOT/'output/verification/vlm-checkpoint-live-proof.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps(proof))


if __name__=='__main__':main()
