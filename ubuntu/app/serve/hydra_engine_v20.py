"""Finite Bonsai-only v20 admission; never clears historical GPU quarantine."""
import hashlib,json,os,time
from pathlib import Path
MODEL='prism-ml/Ternary-Bonsai-2-27B-gguf'
PROFILES={'v20-bonsai-hybrid-16':16,'v20-bonsai-vulkan-full':65}
def digest(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(path,value):
 path=Path(path);tmp=path.with_suffix('.pending')
 with tmp.open('w',encoding='utf8') as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)
def consume(path,run_id):
 path=Path(path);s=json.loads(path.read_text());marker=path.parent/(run_id+'-gpu-started.json')
 if marker.exists():raise ValueError('V20_REQUEST_ALREADY_STARTED')
 if s.get('state')!='ARMED' or type(s.get('used')) is not int or not 0<=s['used']<12 or s.get('max_requests')!=12:raise ValueError('V20_HALTED_CLOSED_OR_EXHAUSTED')
 s['used']+=1;write(path,s)
 with marker.open('x') as f:json.dump(dict(run_id=run_id,started_at=time.time(),used=s['used']),f);f.flush();os.fsync(f.fileno())
def load(require_active=True):
 if os.environ.get('HYDRA_LAB_MODE')!='1':raise ValueError('V20_LAB_REQUIRED')
 p=Path(os.environ['HYDRA_V20_GRANT']);g=json.loads(p.read_text());state=Path(g['counter']);s=json.loads(state.read_text())
 if s.get('grant_sha256')!=digest(p) or type(s.get('used')) is not int or not 0<=s['used']<=12 or s.get('max_requests')!=12:raise ValueError('V20_INVALID_GRANT')
 if require_active and (s.get('state')!='ARMED' or s['used']>=12 or time.time()>g['expires_at']):raise ValueError('V20_CLOSED_HALTED_EXHAUSTED_OR_EXPIRED')
 for p,h in g['protected'].items():
  if digest(p)!=h:raise ValueError('V20_PROTECTED_IDENTITY_CHANGED')
 return g,state

def available():
 try:load();return True
 except (OSError,KeyError,ValueError,TypeError):return False

def validate(body):
 g,state=load()
 if body.get('model_id')!=MODEL or body.get('profile') not in PROFILES or body.get('samples')!=1 or body.get('thinking')!='off':raise ValueError('V20_TARGET_PROFILE_REQUIRED')
 spec=g['requests'].get(body.get('prompt_id'))
 if spec!=body:raise ValueError('V20_FROZEN_REQUEST_MISMATCH')
 return g,state

def allow_spawn(request,argv):
 if request.get('profile') not in PROFILES:return False
 g,_=load();binary=str(Path(g['runtime'])/'llama-server.exe')
 if str(argv[0])!=binary:return False
 if list(argv)==[binary,'--list-devices']:return True
 expected=g['commands'].get(request.get('workload'))
 actual=list(argv)
 if '--port' in actual:
  index=actual.index('--port')+1
  if not str(actual[index]).isdigit() or not 1024<=int(actual[index])<=65535:return False
  actual[index]='<PORT>'
 return actual==expected and request.get('model')==MODEL

def preflight(body,run_id,binary,env):
 import psutil,re
 from serve.hydra_execution_v10 import _local,guarded_run,alive
 g,state=validate(body);lease=getattr(_local,'reservation',None)
 if not lease or not lease.handle or lease.row['run_id']!=run_id:raise ValueError('V20_COORDINATOR_REQUIRED')
 if psutil.virtual_memory().available<12*1024**3:raise MemoryError('V20_RAM_MARGIN')
 if digest(g['model'])!=g['model_sha256']:raise ValueError('V20_MODEL_CHANGED')
 for name,h in g['files'].items():
  if digest(Path(g['runtime'])/name)!=h:raise ValueError('V20_RUNTIME_CHANGED')
 owned={c['pid'] for c in lease.row['children'] if alive(c)}
 native={p.info['pid'] for p in psutil.process_iter(['pid','name']) if (p.info['name'] or '').lower() in ('llama-server.exe','llama-cli.exe','llama-completion.exe','qwen36.exe','native_score.exe')}
 if native-owned or len(native)>1:raise ValueError('V20_FOREIGN_NATIVE_RUNTIME')
 probe=guarded_run([str(binary),'--list-devices'],cwd=binary.parent,env=env,capture_output=True,timeout=10,creationflags=0x08000000)
 text=(probe.stdout+probe.stderr).decode(errors='replace');m=re.search(r'Vulkan0: AMD Radeon RX 7900 XTX \(\d+ MiB, (\d+) MiB free\)',text)
 if probe.returncode or not m or int(m.group(1))<(4096 if native else 10240):raise MemoryError('V20_VRAM_MARGIN')
 return int(m.group(1))

def finish(body,row):
 g,state=load(require_active=False);s=json.loads(state.read_text());logpath=Path(row['log_path']);log=logpath.read_text(errors='replace') if logpath.exists() else ''
 severe=any(x in log.lower() for x in ('errordevicelost','out of memory','vk_error','device lost'))
 if severe or not row.get('cleanup') or row.get('status') not in ('RUNNING','PASS'):
  s.update(state='HALTED',reason=row.get('error') or 'native fault or cleanup uncertainty',run_id=row['run_id']);write(state,s)

def public_status():
 try:
  grant,path=load(require_active=False);s=json.loads(path.read_text());active=s['state']=='ARMED' and s['used']<12 and time.time()<=grant.get('expires_at',float('inf'))
  return dict(state=s['state'],used=s['used'],total_limit=12,remaining=12-s['used'],available=active,requests=list(grant['requests'].values()) if active else [],scope='Bonsai PTQ1_0 only; explicit finite v20 grant; historical quarantine unchanged')
 except (OSError,ValueError,KeyError,TypeError):
  try:
   s=json.loads((Path(__file__).resolve().parents[1]/'data/hydra-v20-summary.json').read_text())
   return dict(state=s['state'],used=s['used'],total_limit=12,remaining=12-s['used'],available=False,requests=[])
  except (OSError,ValueError,KeyError,TypeError):return dict(state='NOT_ACTIVE',used=None,total_limit=12,available=False,requests=[])


def halt(reason,run_id):
 _,path=load(require_active=False);state=json.loads(path.read_text())
 if state['state']!='CLOSED':state.update(state='HALTED',reason=str(reason),run_id=run_id);write(path,state)
