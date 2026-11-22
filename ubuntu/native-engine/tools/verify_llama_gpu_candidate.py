import json,sys,time,threading,concurrent.futures,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from serve.optional_backends import OptionalBackends
from serve.update_center import file_sha256
from unittest.mock import patch
import subprocess
from tools.verify_audio_update_cpu import call
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--candidate',required=True,type=Path);parser.add_argument('--model',required=True,type=Path);args=parser.parse_args()
root=Path(__file__).resolve().parents[1];folder=args.candidate.resolve();manifest=json.loads((folder/'CANDIDATE-MANIFEST.json').read_text(encoding='utf-8'))
if not folder.is_relative_to((root/'output/updates/candidates').resolve()):raise ValueError('Candidate outside isolated folder')
if not manifest.get('source','').startswith('https://github.com/unslothai/llama.cpp/releases/download/') or not manifest['source'].endswith('windows-x64-rocm-gfx110X.zip'):raise ValueError('Unsupported candidate GPU package')
if call('/inference-backends')['status']!='idle' or call('/metrics')['live']['state']!='unloaded':raise RuntimeError('An engine is active')
for row in manifest['files']:
 p=(folder/row['path']).resolve()
 if not p.is_relative_to(folder.resolve()) or file_sha256(p)!=row['sha256']:raise RuntimeError('Candidate integrity failure')
model=args.model.resolve()
if not model.is_file() or model.stat().st_size>1024**3:raise ValueError('Select a local GGUF below 1 GiB')
original=Path.home()/'.unsloth/llama.cpp/build/bin/Release/llama-server.exe';before=file_sha256(original)
manager=OptionalBackends(root,discover_models=False);manager.binary=folder/'llama-server.exe';manager.candidate_validation=True
report={'passed':False,'scope':'One bounded small-GGUF GPU response; not 125B performance or long-term stability','version':manifest['source'].split('/releases/download/',1)[1].split('/',1)[0],'candidate':str(folder),'archive_sha256':manifest['sha256'],'started_at':time.time()};cancel=threading.Event();pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
real_popen=subprocess.Popen
patcher=None
try:
 def detailed_popen(command,*args,**kwargs):
  if isinstance(command,list) and '--port' in command and Path(command[0]).resolve()==manager.binary.resolve():command=[*command,'-lv','5']
  return real_popen(command,*args,**kwargs)
 patcher=patch('serve.optional_backends.subprocess.Popen',detailed_popen);patcher.start()
 manager.start({'mode':'gguf','model_path':model,'gpu':True,'context':1024,'context_mode':'manual','fit_mode':'manual','runtime':{'threads':2,'threads_batch':2,'batch':128,'micro_batch':128}},True)
 deadline=time.monotonic()+75
 while time.monotonic()<deadline:
  state=manager.status(include_models=False)
  if state['status']=='ready':break
  if state['status']=='error':raise RuntimeError(state['error'])
  time.sleep(.25)
 else:raise TimeoutError('GPU candidate loading deadline')
 future=pool.submit(lambda:list(manager.chat({'messages':[{'role':'user','content':'Reply with a short greeting.'}],'max_tokens':16,'stream':False,'temperature':0},cancel)))
 events=future.result(timeout=30);report['response']=events;answer=''.join(e.get('choices',[{}])[0].get('message',{}).get('content') or '' for e in events)
 log=(root/'output/verification/optional-backend-server.log').read_text(encoding='utf-8',errors='replace')
 report['answer']=answer
 import re
 offloaded=re.search(r'offloaded\s+([1-9]\d*)/\d+\s+layers to GPU',log,re.I)
 if not answer.strip() or not offloaded:raise RuntimeError('GPU response/offload not confirmed')
 report.update(passed=True,state=state,response=events,answer=answer,gpu_offload_confirmed=True)
except Exception as e:report['error']=str(e)
finally:
 cancel.set();manager.close();patcher.stop() if patcher else None;pool.shutdown(wait=False,cancel_futures=True)
 log_path=root/'output/verification/optional-backend-server.log'
 if log_path.exists():(folder/'GPU-validation.log').write_bytes(log_path.read_bytes())
 report.update(finished_at=time.time(),original_binary_sha256_before=before,original_binary_sha256_after=file_sha256(original),original_preserved=before==file_sha256(original),owned_process_stopped=manager.child is None)
 (folder/'GPU-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:report.get(k) for k in ['passed','error','answer','gpu_offload_confirmed','owned_process_stopped','original_preserved']}))
raise SystemExit(0 if report['passed'] else 1)
