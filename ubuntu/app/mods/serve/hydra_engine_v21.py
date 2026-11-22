"""Independent finite Bonsai grant. No historical ticket or quarantine is cleared."""
import json,math,os,re,time
from pathlib import Path
from serve.hydra_engine_v20 import MODEL,digest,write,consume as _consume
PROFILE='v21-bonsai-hybrid'

def consume(path,request_id):
 try:_consume(path,request_id)
 except ValueError as exc:raise ValueError(str(exc).replace('V20_','V21_')) from exc

def load(require_active=True):
 if os.environ.get('HYDRA_LAB_MODE')!='1':raise ValueError('V21_LAB_REQUIRED')
 p=Path(os.environ['HYDRA_V21_GRANT']);g=json.loads(p.read_text(encoding='utf8'));counter=Path(g['counter']);s=json.loads(counter.read_text(encoding='utf8'))
 if g.get('version')!=21 or s.get('grant_sha256')!=digest(p) or type(s.get('used')) is not int or not 0<=s['used']<=12 or s.get('max_requests')!=12:raise ValueError('V21_INVALID_GRANT')
 if require_active and (s['state']!='ARMED' or s['used']>=12 or time.time()>g['expires_at']):raise ValueError('V21_CLOSED_HALTED_EXHAUSTED_OR_EXPIRED')
 for file,h in g['protected'].items():
  if digest(file)!=h:raise ValueError('V21_PROTECTED_IDENTITY_CHANGED')
 return g,counter

def available():
 try:load();return True
 except (OSError,ValueError,KeyError,TypeError):return False

def validate(body):
 g,c=load();layers=body.get('gpu_layers')
 if body.get('profile')!=PROFILE or body.get('model_id')!=MODEL or type(layers) is not int or not 1<=layers<=g['total_layers']:raise ValueError('V21_OFFLOAD_NOT_ADMITTED')
 if g['requests'].get(body.get('prompt_id'))!=body:raise ValueError('V21_FROZEN_REQUEST_MISMATCH')
 if json.loads(c.read_text())['used']+body['samples']>12:raise ValueError('V21_INSUFFICIENT_BUDGET')
 return g,c

def validate_native_options(body,options):
 g,_=load();expected=dict(g['options'])
 if body.get('checkpoint'):expected['cache_prompt']=True
 for key in ('context','threads','affinity_cpus','seed','cache_prompt','mmap','model_io','max_tokens'):
  if options.get(key)!=expected.get(key):raise ValueError('V21_NATIVE_OPTIONS_MISMATCH: '+key)

def allow_spawn(request,argv):
 if request.get('profile')!=PROFILE:return False
 g,_=load();binary=str(Path(g['runtime'])/'llama-server.exe');actual=list(map(str,argv))
 if actual==[binary,'--list-devices']:return True
 for flag,replacement in (('--port','<PORT>'),('--slot-save-path','<STATE>')):
  if flag in actual:
   i=actual.index(flag)+1
   if flag=='--port' and (not actual[i].isdigit() or not 1024<=int(actual[i])<=65535):return False
   if flag=='--slot-save-path':
    root=Path(__file__).resolve().parents[1]/'data/hydra-benchmark-registry/runs'/request['run_id']/'native-state'
    if Path(actual[i]).resolve()!=root.resolve():return False
   actual[i]=replacement
 return request.get('model')==MODEL and actual==g['commands'].get(request.get('workload'))

def preflight(body,run_id,binary,env):
 import psutil
 from serve.hydra_execution_v10 import _local,guarded_run,alive
 g,c=load();lease=getattr(_local,'reservation',None)
 if not lease or not lease.handle or lease.row['run_id']!=run_id:raise ValueError('V21_COORDINATOR_REQUIRED')
 if psutil.virtual_memory().available<12*1024**3:raise MemoryError('V21_RAM_MARGIN')
 if digest(g['model'])!=g['model_sha256']:raise ValueError('V21_MODEL_CHANGED')
 for name,h in g['files'].items():
  if digest(Path(g['runtime'])/name)!=h:raise ValueError('V21_RUNTIME_CHANGED')
 owned={c['pid'] for c in lease.row['children'] if alive(c)}
 native={p.info['pid'] for p in psutil.process_iter(['pid','name']) if (p.info['name'] or '').lower() in ('llama-server.exe','llama-cli.exe','llama-completion.exe','qwen36.exe','native_score.exe')}
 if native-owned or len(native)>1:raise ValueError('V21_FOREIGN_NATIVE_RUNTIME')
 probe=guarded_run([str(binary),'--list-devices'],cwd=binary.parent,env=env,capture_output=True,timeout=10,creationflags=0x08000000)
 text=(probe.stdout+probe.stderr).decode(errors='replace');m=re.search(r'Vulkan0: AMD Radeon RX 7900 XTX \(\d+ MiB, (\d+) MiB free\)',text)
 required=4096 if native else math.ceil(Path(g['model']).stat().st_size/1024**2)+1536+4096
 if probe.returncode or not m or int(m[1])<required:raise MemoryError('V21_VRAM_MARGIN; required free MiB='+str(required))
 return int(m[1])

def halt(reason,run_id):
 _,p=load(False);s=json.loads(p.read_text())
 if s['state']!='CLOSED':s.update(state='HALTED',reason=str(reason),run_id=run_id);write(p,s)

def finish(body,row):
 path=Path(row['log_path']);log=path.read_text(errors='replace').lower() if path.exists() else ''
 if any(x in log for x in ('errordevicelost','out of memory','vk_error','device lost','vulkan error')) or not row.get('cleanup') or row.get('status') not in ('RUNNING','PASS'):halt(row.get('error') or 'native fault or cleanup uncertainty',row['run_id'])

def public_status():
 try:
  g,p=load(False);s=json.loads(p.read_text());active=s['state']=='ARMED' and s['used']<12 and time.time()<g['expires_at']
  return dict(state=s['state'],used=s['used'],remaining=12-s['used'],total_limit=12,available=active,total_layers=g['total_layers'],requests=list(g['requests'].values()) if active else [],scope='Finite v21 Bonsai application validation; no historical quarantine override outside this grant')
 except (OSError,ValueError,KeyError,TypeError):
  try:return dict(json.loads((Path(__file__).resolve().parents[1]/'data/hydra-v21-summary.json').read_text()),available=False,requests=[])
  except (OSError,ValueError):return dict(state='NOT_ACTIVE',available=False,requests=[])
