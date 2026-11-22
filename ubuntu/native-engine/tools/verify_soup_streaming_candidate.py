import json,subprocess,time,uuid
from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()))
from tools.verify_audio_update_cpu import call
from serve.gpu_lease import GpuLease
root=Path.cwd()
assert call('/metrics')['live']['state']=='unloaded' and call('/inference-backends')['status']=='idle'
proof=json.loads((root/'output/verification/soup-0752-gpu-real.json').read_text())
folder=root/'output/verification'/('soup-streaming-'+uuid.uuid4().hex[:8]);folder.mkdir()
active=json.loads((root/'data/soup-package-selection.json').read_text())['active']
command=[str(Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'),'-X','utf8','tools/train_soup_streaming_candidate.py','--device','cuda','--package-root',active['package_root'],'--model',proof['workflow']['base'],'--train','output/verification/training-smoke-train.jsonl','--validation','output/verification/training-smoke-validation.jsonl','--output',str(folder/'training'),'--steps','1','--length','64']
start=time.monotonic()
with GpuLease(root,'soup-streaming-probe'):
 with (folder/'worker.log').open('wb') as log:
  try:result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=90)
  except subprocess.TimeoutExpired:result=type('TimedOut',(),{'returncode':124})()
report={'exit_code':result.returncode,'seconds':time.monotonic()-start,'folder':str(folder),'scope':'One local 135M step; streaming verification only, not a 125B benchmark'}
path=folder/'training/workflow.json'
if path.exists():report['workflow']=json.loads(path.read_text())
report['passed']=result.returncode==0 and report.get('workflow',{}).get('export_greedy_tokens_equal') is True
(root/'output/verification/soup-streaming-candidate-real.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
