import hashlib,json,subprocess,uuid
from pathlib import Path
root=Path.cwd();proof=json.loads((root/'output/verification/conversation-training/api-result.json').read_text(encoding='utf-8'));output=root/'output/verification'/('soup-cpu-regression-'+uuid.uuid4().hex[:8]);log=output.with_suffix('.log')
command=[str(root/'.venv-soup/Scripts/python.exe'),'-X','utf8',str(root/'tools/train_soup_cpu.py'),'--model',proof['model'],'--train',str(root/'output/verification/training-smoke-train.jsonl'),'--validation',str(root/'output/verification/training-smoke-validation.jsonl'),'--output',str(output),'--steps','2','--length','64','--rank','4','--alpha','8','--learning-rate','0.0002','--accumulation','2','--seed','9','--checkpointing']
with log.open('wb') as stream:result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
workflow=json.loads((output/'workflow.json').read_text(encoding='utf-8'))
assert result.returncode==0 and workflow['status']=='complete' and workflow['export_logits_verified'],str(log)
path=root/'data/soup-runtime-validation.json';data=json.loads(path.read_text(encoding='utf-8'));data.update(bridge_sha256=hashlib.sha256((root/'tools/train_soup_cpu.py').read_bytes()).hexdigest(),evidence=str(output.relative_to(root)/'workflow.json'));path.write_text(json.dumps(data,indent=2),encoding='utf-8');print('Soup CPU regression complete; validated bridge identity refreshed')
