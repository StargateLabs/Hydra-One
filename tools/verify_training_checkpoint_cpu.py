import os,json,subprocess,uuid,urllib.request
from pathlib import Path
from serve.gpu_lease import GpuLease
root=Path.cwd()
with urllib.request.urlopen('http://127.0.0.1:8088/metrics') as response:assert json.load(response)['live']['state']=='unloaded'
with urllib.request.urlopen('http://127.0.0.1:8088/inference-backends') as response:assert json.load(response)['status']=='idle'
python=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
model=next((root.parent/'Strata-data/models/optional/HuggingFaceTB--SmolLM2-135M-Instruct').glob('*/config.json')).parent
identity=uuid.uuid4().hex
first=root/'output/training'/('checkpoint-first-'+identity);second=root/'output/training'/('checkpoint-resume-'+identity)
base=[str(python),str(root/'tools/train_local_lora.py'),'--model',str(model),'--train',str(root/'output/verification/training-smoke-train.jsonl'),'--validation',str(root/'output/verification/training-smoke-validation.jsonl'),'--length','32','--save-steps','1']
env={**os.environ,'CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1'}
with GpuLease(root,'training-checkpoint-cpu-test'):
    for name,command in [('save',base+['--output',str(first),'--steps','2']),('resume',base+['--output',str(second),'--steps','3','--resume-checkpoint',str(first/'trainer/checkpoint-2')])]:
        with (root/'output/verification'/('checkpoint-'+name+'.log')).open('w',encoding='utf-8') as log:
            process=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        if process.returncode:raise RuntimeError(name+' failed; inspect checkpoint-'+name+'.log')
    a=json.loads((first/'workflow.json').read_text());b=json.loads((second/'workflow.json').read_text())
    assert a['status']==b['status']=='complete' and a['export_logits_verified'] and b['export_logits_verified']
    assert b['completed_steps']==3
    (root/'output/verification/training-checkpoint-resume-real.json').write_text(json.dumps({'save':a,'resume':b,'gpu_used':False},indent=2),encoding='utf-8')
print('Real CPU training: saved at step 2, resumed to step 3, both exports verified')
