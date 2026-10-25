"""Windows-only lab admission. No stale lease is removed without process verification."""
import ctypes, functools, hashlib, json, os, subprocess, threading, time, uuid
from ctypes import wintypes as W
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1]/'data/hydra-execution-v10'
_local=threading.local()
class AdmissionError(RuntimeError): pass
def valid_mutex_acl(value):
 """Accept Windows canonical AI control flag, never inherited/additional ACEs.

 P remains mandatory; the two exact explicit principals and rights are unchanged.
 https://learn.microsoft.com/windows/win32/secauthz/security-descriptor-string-format
 """
 return value.replace('0x1f0001','GA') in ('D:P(A;;GA;;;SY)(A;;GA;;;OW)','D:PAI(A;;GA;;;SY)(A;;GA;;;OW)')
class BasicLimits(ctypes.Structure):
 _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',W.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',W.DWORD),('affinity',ctypes.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
class IOCounters(ctypes.Structure):_fields_=[(name,ctypes.c_uint64) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
class ExtendedLimits(ctypes.Structure):_fields_=[('basic',BasicLimits),('io',IOCounters),('process_limit',ctypes.c_size_t),('job_limit',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]


def identity(pid=None):
 p=psutil.Process(pid or os.getpid())
 return dict(pid=p.pid,ppid=p.ppid(),created=p.create_time(),executable=p.exe())
def alive(entry):
 try:return abs(psutil.Process(entry['pid']).create_time()-entry['created'])<.01
 except psutil.NoSuchProcess:return False
 except (psutil.Error,KeyError,TypeError):raise AdmissionError('UNKNOWN_OWNER; fail closed')
def write(path,value):
 tmp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(value,indent=2),encoding='utf8');os.replace(tmp,path)
class Reservation:
 def __init__(self,request,root=None):
  self.root=Path(root) if root else ROOT;self.path=self.root/'lease.json';self.request=request;self.handle=None;self.children=[];self.thread=None;self.job=None;self.memory_lease=None
 def acquire(self):
  if os.name!='nt':raise AdmissionError('Windows named mutex unavailable')
  self.root.mkdir(parents=True,exist_ok=True)
  k=ctypes.WinDLL('kernel32',use_last_error=True);self.k=k
  k.CreateMutexW.argtypes=[W.LPVOID,W.BOOL,W.LPCWSTR];k.CreateMutexW.restype=W.HANDLE
  k.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];k.WaitForSingleObject.restype=W.DWORD
  k.ReleaseMutex.argtypes=[W.HANDLE];k.CloseHandle.argtypes=[W.HANDLE]
  # Fixed absolute scope, independent of working directory. Default token DACL;
  # custom ACL attestation remains an explicit gate, not an assumed guarantee.
  name='Local\\HYDRA.ONE.v10.'+hashlib.sha256(str(self.root.resolve()).casefold().encode()).hexdigest()[:24]
  adv=ctypes.WinDLL('advapi32',use_last_error=True)
  adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[W.LPCWSTR,W.DWORD,ctypes.POINTER(W.LPVOID),ctypes.POINTER(W.DWORD)]
  adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype=W.BOOL
  class SA(ctypes.Structure):_fields_=[('length',W.DWORD),('descriptor',W.LPVOID),('inherit',W.BOOL)]
  sd=W.LPVOID();size=W.DWORD()
  if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:P(A;;GA;;;SY)(A;;GA;;;OW)',1,ctypes.byref(sd),ctypes.byref(size)):raise ctypes.WinError(ctypes.get_last_error())
  sa=SA(ctypes.sizeof(SA),sd,False)
  try:self.handle=k.CreateMutexW(ctypes.byref(sa),False,name)
  finally:
   k.LocalFree.argtypes=[W.LPVOID];k.LocalFree(sd)

  if not self.handle:
   error=ctypes.get_last_error()
   if error==5:raise AdmissionError('BLOCKED_BUSY; mutex access denied; ownership cannot be attested')
   raise ctypes.WinError(error)
  adv.GetKernelObjectSecurity.argtypes=[W.HANDLE,W.DWORD,W.LPVOID,W.DWORD,ctypes.POINTER(W.DWORD)];adv.GetKernelObjectSecurity.restype=W.BOOL
  needed=W.DWORD();adv.GetKernelObjectSecurity(self.handle,4,None,0,ctypes.byref(needed))
  if not needed.value or needed.value>65536:k.CloseHandle(self.handle);self.handle=None;raise AdmissionError('MUTEX_SECURITY_UNKNOWN')
  buffer=ctypes.create_string_buffer(needed.value)
  if not adv.GetKernelObjectSecurity(self.handle,4,buffer,len(buffer),ctypes.byref(needed)):k.CloseHandle(self.handle);self.handle=None;raise AdmissionError('MUTEX_SECURITY_UNKNOWN')
  rendered=W.LPWSTR();adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes=[W.LPVOID,W.DWORD,W.DWORD,ctypes.POINTER(W.LPWSTR),ctypes.POINTER(W.DWORD)];adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype=W.BOOL
  if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(buffer,1,4,ctypes.byref(rendered),None):k.CloseHandle(self.handle);self.handle=None;raise AdmissionError('MUTEX_SECURITY_UNKNOWN')
  try:actual_acl=rendered.value
  finally:k.LocalFree(ctypes.cast(rendered,W.LPVOID))
  if not valid_mutex_acl(actual_acl):k.CloseHandle(self.handle);self.handle=None;raise AdmissionError('MUTEX_SECURITY_MISMATCH: '+actual_acl)
  wait=k.WaitForSingleObject(self.handle,0)
  if wait not in (0,128):k.CloseHandle(self.handle);self.handle=None;self.reject('BLOCKED_BUSY');raise AdmissionError('BLOCKED_BUSY')
  try:
   if self.path.exists():
    old=json.loads(self.path.read_text(encoding='utf8'))
    if old.get('state')!='RELEASED':
     if not all(k in old for k in ('owner','children','spawn_uncertain')):raise AdmissionError('UNKNOWN_OWNER; fail closed')
     if old.get('spawn_uncertain') or alive(old.get('owner',{})) or any(alive(c) for c in old.get('children',[])):raise AdmissionError('BLOCKED_BUSY; unreleased or uncertain ownership')
     if any(p.info['ppid']==old.get('owner',{})['pid'] for p in psutil.process_iter(['ppid'])):raise AdmissionError('BLOCKED_BUSY; residual descendant')
     write(self.root/('recovered-'+uuid.uuid4().hex+'.json'),old)
   foreign=[p.info for p in psutil.process_iter(['pid','name','create_time']) if (p.info.get('name') or '').lower() in ('llama-server.exe','llama-cli.exe','llama-completion.exe','native_score.exe','native-score-v11.exe','native-score-v13.exe','native-score-v14.exe','native-score-recovery.exe','qwen36.exe','audiocpp_server.exe','locate-anything-cli.exe','yue-synth.exe','sd-cli.exe','strata.exe')]
   if foreign:self.reject('FOREIGN_RUNTIME_PRESENT');raise AdmissionError('BLOCKED_BUSY; foreign runtime present; no process stopped')
   self.thread=threading.get_ident();self.row=dict(run_id=self.request.get('run_id',uuid.uuid4().hex),owner=identity(),request=self.request,state='PRECHECK',children=[],spawn_uncertain=False,events=[],mutex=name,permissions=actual_acl)
   # Reserve before creating the private Job. This is a commit envelope, not
   # proof of physical residency or a grant for an unbounded GPU runtime.
   memory_limit=self.request.get('memory_limit_bytes')
   if self.request.get('memory_component_plan') is not None and memory_limit is None:raise AdmissionError('COMPONENT_PLAN_REQUIRES_ENFORCED_JOB_LIMIT')
   if memory_limit is not None:
    from serve.hydra_memory_budget import reserve_job_commit
    if type(memory_limit) is not int or not 32*1024**2<=memory_limit<=128*1024**3:raise AdmissionError('INVALID_COMMIT_MEMORY_LIMIT')
    self.memory_lease=reserve_job_commit(self.row['run_id'],memory_limit,psutil.virtual_memory().available,self.request.get('memory_component_plan'))
    self.row['memory_reservation']=dict(owner=self.row['run_id'],ram_commit_bytes=memory_limit,vram_capability=False,state='RESERVED')
   if ctypes.sizeof(ctypes.c_void_p)!=8 or ctypes.sizeof(ExtendedLimits)!=144:raise AdmissionError('JOB_LAYOUT_UNVERIFIED')
   k.CreateJobObjectW.argtypes=[W.LPVOID,W.LPCWSTR];k.CreateJobObjectW.restype=W.HANDLE
   k.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,W.LPVOID,W.DWORD];k.SetInformationJobObject.restype=W.BOOL
   k.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];k.AssignProcessToJobObject.restype=W.BOOL
   k.QueryInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,W.LPVOID,W.DWORD,ctypes.POINTER(W.DWORD)];k.QueryInformationJobObject.restype=W.BOOL
   self.job=k.CreateJobObjectW(None,None)
   if not self.job:raise ctypes.WinError(ctypes.get_last_error())
   limits=ExtendedLimits();limits.basic.flags=0x2000
   memory_limit=self.request.get('memory_limit_bytes')
   if memory_limit is not None:
    if type(memory_limit) is not int or not 32*1024**2<=memory_limit<=128*1024**3:raise AdmissionError('INVALID_COMMIT_MEMORY_LIMIT')
    limits.basic.flags|=0x300
    limits.process_limit=memory_limit;limits.job_limit=memory_limit
   if not k.SetInformationJobObject(self.job,9,ctypes.byref(limits),ctypes.sizeof(limits)):raise ctypes.WinError(ctypes.get_last_error())
   self.row['job_policy']='KILL_ON_JOB_CLOSE; no memory limit; descendants stay in private Job'
   if memory_limit is not None:
    actual=ExtendedLimits();returned=W.DWORD()
    if not k.QueryInformationJobObject(self.job,9,ctypes.byref(actual),ctypes.sizeof(actual),ctypes.byref(returned)):raise ctypes.WinError(ctypes.get_last_error())
    if returned.value!=ctypes.sizeof(actual) or actual.basic.flags&0x300!=0x300 or actual.process_limit!=memory_limit or actual.job_limit!=memory_limit:raise AdmissionError('COMMIT_MEMORY_LIMIT_READBACK_MISMATCH')
    self.row['memory_policy']=dict(kind='WINDOWS_PROCESS_AND_JOB_COMMIT_LIMIT',limit_bytes=memory_limit,flags=actual.basic.flags,readback_verified=True,physical_ram_hard_cap=False,peak_accounting='High-water counters may include refused allocation attempts; not an RSS bound')
    self.row['job_policy']='KILL_ON_JOB_CLOSE; process and aggregate Job committed-memory limits; not physical RAM'
   if self.memory_lease:self.memory_lease.attach()
   self.transition('LOCKED');_local.reservation=self;return self
  except Exception:
   if self.job:k.CloseHandle(self.job);self.job=None
   if self.memory_lease:
    self.memory_lease.release(lambda: True);self.memory_lease=None
   k.ReleaseMutex(self.handle);k.CloseHandle(self.handle);self.handle=None;raise
 def reject(self,reason):
  write(self.root/('rejected-'+uuid.uuid4().hex+'.json'),dict(status='BLOCKED_BUSY',request=self.request,applicant=identity(),reason=reason,at=time.time()))
 def transition(self,state):
  self.row['state']=state;self.row['events'].append(dict(state=state,monotonic=time.monotonic(),at=time.time()));write(self.path,self.row)
 def spawn(self,*args,**kwargs):
  if self.thread!=threading.get_ident() or not self.handle:raise AdmissionError('NO_VALID_RESERVATION')
  command=args[0] if args else kwargs.get('args');text=' '.join(map(str,command)) if not isinstance(command,str) else command
  marker=Path(__file__).resolve().parents[1]/'data/hydra-v8-safety-stop.json'
  argv=list(command) if not isinstance(command,str) else __import__('shlex').split(command)
  # Mandatory native-MoE guard, independent of optional FCC persistence or
  # executable naming. An alternate adapter cannot bypass it with policy OFF.
  from serve.hydra_native_admission import guard_owned_launch
  guard_owned_launch(Path(__file__).resolve().parents[1],list(map(str,argv)),self.row['request'],dict(kwargs.get('env') or os.environ))
  from serve.hydra_feature_control import policy_exists,check_native_policy
  if policy_exists():check_native_policy(argv,self.row.get('request',{}))
  positive_layers=any(str(arg) in ('-ngl','--gpu-layers','--n-gpu-layers') and i+1<len(argv) and str(argv[i+1]) not in ('0','0.0') for i,arg in enumerate(argv))
  build_only=self.request.get('backend')=='BUILD_ONLY' and Path(str(argv[0])).name.lower() in ('cmd.exe','cmake','cmake.exe','ninja','ninja.exe','clang.exe','clang++.exe','g++','g++.exe','gcc','gcc.exe')
  if self.memory_lease and not build_only and (positive_layers or any(x in text.lower() for x in ('vulkan','rocm','--device gpu'))):raise AdmissionError('VRAM_COMPONENT_LIMIT_UNENFORCED; RAM Job reservation grants no GPU budget')
  recovery_allowed=False
  if self.request.get('profile')=='v21-bonsai-hybrid':
   from serve.hydra_engine_v21 import allow_spawn
   recovery_allowed=allow_spawn(self.row['request'],argv)
   if not recovery_allowed:raise AdmissionError('V21_NATIVE_LAUNCH_DENIED')
  if self.request.get('profile') in ('v20-bonsai-hybrid-16','v20-bonsai-vulkan-full'):
   from serve.hydra_engine_v20 import allow_spawn
   recovery_allowed=allow_spawn(self.row['request'],argv)
   if not recovery_allowed:raise AdmissionError('V20_NATIVE_LAUNCH_DENIED')
  if self.request.get('profile') in ('v8-v18-cpu-qwen','v8-v18-gpu-qwen','v8-v19-cpu-qwen','v8-v19-gpu-qwen'):
   from serve.hydra_acceptance_campaign import allow_spawn
   recovery_allowed=allow_spawn(self.row['request'],argv)
   if not recovery_allowed:raise AdmissionError('V18_NATIVE_LAUNCH_DENIED')
  if self.request.get('profile')=='v8-recovery-qwen':
   from serve.hydra_gpu_recovery_v16 import allow_spawn
   recovery_allowed=allow_spawn(self.row['request'],argv)
   if not recovery_allowed:raise AdmissionError('RECOVERY_NATIVE_LAUNCH_DENIED')
  metadata_help=len(argv)==2 and Path(str(argv[0])).name.lower()=='llama-server.exe' and argv[1] in ('--help','--version')
  if marker.exists() and not build_only and not recovery_allowed and not metadata_help and (positive_layers or any(x in text.lower() for x in ('vulkan','rocm','-ngl 29','-ngl 65','-ngl 99','--gpu-layers','--n-gpu-layers','--device gpu'))):raise AdmissionError('GPU_QUARANTINED; separate recovery gate required')
  kwargs['creationflags']=kwargs.get('creationflags',0)|4
  kwargs['env']=dict(kwargs.get('env') or os.environ,HYDRA_ADMISSION_LEASE_FILE=str(self.path.resolve()))
  # Never inherit a parent's native suballocation capability. Only this owned
  # reservation may hand component ceilings to its child process.
  kwargs['env'].pop('HYDRA_MEMORY_OWNER',None)
  kwargs['env'].pop('HYDRA_NATIVE_MEMORY_ENVELOPE',None)
  if self.memory_lease:kwargs['env'].update(self.memory_lease.native_environment())
  self.row['spawn_uncertain']=True;self.row['expected_command']=command;self.transition('STARTING')
  try:child=subprocess.Popen(*args,**kwargs)
  except Exception:self.row['spawn_uncertain']=False;self.transition('CLEANUP');raise
  if not self.k.AssignProcessToJobObject(self.job,W.HANDLE(int(child._handle))):
   error=ctypes.get_last_error();child.terminate();child.wait(timeout=3);raise AdmissionError('JOB_ASSIGNMENT_FAILED: '+str(error))
  info=identity(child.pid);self.children.append(child);self.row['children'].append(info)
  selected=self.row['request'].get('cpu_affinity')
  if selected:
   try:
    process=psutil.Process(child.pid);process.cpu_affinity(selected);actual=process.cpu_affinity()
    if set(actual)!=set(selected):raise AdmissionError('CPU_AFFINITY_READBACK_MISMATCH')
    info['cpu_affinity_before_resume']=actual
   except BaseException:
    child.terminate();child.wait(3);self.row['spawn_uncertain']=False;self.transition('CLEANUP');raise
  self.row['spawn_uncertain']=False;self.transition('RUNNING');psutil.Process(child.pid).resume();return child
 def job_members(self):
  buffer=ctypes.create_string_buffer(8+8*4096);length=W.DWORD()
  if not self.k.QueryInformationJobObject(self.job,3,buffer,len(buffer),ctypes.byref(length)):raise AdmissionError('JOB_MEMBERSHIP_UNKNOWN')
  assigned,count=ctypes.cast(buffer,ctypes.POINTER(W.DWORD*2)).contents
  if count>4096 or assigned!=count:raise AdmissionError('JOB_MEMBERSHIP_INCOMPLETE')
  return list((ctypes.c_size_t*count).from_buffer(buffer,8))
 def verify_cleanup(self):
  self.transition('CLEANUP')
  if self.job_members() or self.row['spawn_uncertain'] or any(alive(c) for c in self.row['children']):raise AdmissionError('CLEANUP_UNVERIFIED; reservation retained')
  # The private Job proves descendant membership; numeric PPIDs may be reused.
  self.transition('VERIFIED_TERMINAL')
 def release(self,persisted=False):
  if self.row['state']!='VERIFIED_TERMINAL':self.transition('CLEANUP')
  if not persisted or self.job_members() or self.row['spawn_uncertain'] or any(alive(c) for c in self.row['children']):raise AdmissionError('CLEANUP_UNVERIFIED; reservation retained')
  # The private Job proves descendant membership; numeric PPIDs may be reused.
  if self.row['state']!='VERIFIED_TERMINAL':self.transition('VERIFIED_TERMINAL')
  if self.memory_lease:
   self.memory_lease.release(self._memory_cleanup_attested);self.memory_lease=None
   self.row['memory_reservation']['state']='RELEASED_AFTER_VERIFIED_JOB_CLEANUP'
  self.transition('RELEASED');write(self.root/('run-'+self.row['run_id']+'.json'),self.row)
  self.k.CloseHandle(self.job);self.job=None
  self.k.ReleaseMutex(self.handle);self.k.CloseHandle(self.handle);self.handle=None;_local.reservation=None
 def _memory_cleanup_attested(self):
  return self.row['state']=='VERIFIED_TERMINAL' and not self.row['spawn_uncertain'] and not self.job_members() and not any(alive(c) for c in self.row['children'])

def guarded_run(*args,**kwargs):
 capture=kwargs.pop('capture_output',False);timeout=kwargs.pop('timeout',None);check=kwargs.pop('check',False)
 if capture:kwargs.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 child=guarded_popen(*args,**kwargs)
 try:out,err=child.communicate(timeout=timeout)
 except BaseException:
  child.kill();child.communicate();raise
 result=subprocess.CompletedProcess(args[0],child.returncode,out,err)
 if check:result.check_returncode()
 return result

def guarded_popen(*args,**kwargs):
 lease=getattr(_local,'reservation',None)
 if lease is None:raise AdmissionError('NO_VALID_RESERVATION; direct lab launcher denied')
 return lease.spawn(*args,**kwargs)
def apply_owned_affinity(pid,default_cpus):
 """Adapter-specific defaults must not overwrite the admitted E-core mask."""
 lease=getattr(_local,'reservation',None)
 selected=lease.row['request'].get('cpu_affinity') if lease else None
 process=psutil.Process(pid);process.cpu_affinity(selected or default_cpus)
 actual=process.cpu_affinity()
 if selected and set(actual)!=set(selected):raise AdmissionError('CPU_AFFINITY_READBACK_MISMATCH')
 return actual
def notify_gpu_fault(body,reason,run_id):
 profile=body.get('profile','')
 if profile=='v21-bonsai-hybrid':module_name='serve.hydra_engine_v21';variable='HYDRA_V21_GRANT'
 elif profile in ('v20-bonsai-hybrid-16','v20-bonsai-vulkan-full'):module_name='serve.hydra_engine_v20';variable='HYDRA_V20_GRANT'
 else:return False
 if not os.environ.get(variable):return False # rejected before an admitted GPU campaign
 module=__import__(module_name,fromlist=['load','halt'])
 try:module.load(require_active=False)
 except (OSError,KeyError,ValueError,TypeError):return False # invalid grants cannot authorize a later spawn
 module.halt(reason,run_id);return True

def require_application_cleanup(row):
 if row.get('native_state_cleanup') is False:raise AdmissionError('APPLICATION_STATE_CLEANUP_UNVERIFIED')
 if not row.get('cleanup'):raise AdmissionError('APPLICATION_CLEANUP_UNVERIFIED')

def exclusive_execute(fn):
 @functools.wraps(fn)
 def wrapped(workspace,body,*args,**kwargs):
  from serve.hydra_capability_contracts import guard_request
  guard_request(body)
  precheck=getattr(getattr(workspace,'lab',None),'features',None)
  if precheck is not None:precheck.resolve(body) # OFF/dependency refusal before acquiring Job/mutex
  if getattr(_local,'reservation',None):raise AdmissionError('BLOCKED_BUSY; nested runner denied')
  key=kwargs.get('_key') or uuid.uuid4().hex
  # Bound the complete owned process tree before any child is resumed. This is
  # committed virtual memory, independent from the existing sampled RSS guard.
  model=body.get('model_id','local/Qwen3-0.6B-Q8_0')
  commit_gib=24 if model in ('prism-ml/Ternary-Bonsai-2-27B-gguf','huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF','cdiamond/Qwen3.8-27B-iMatrix-NVFP4-MTP-GGUF','Serveurperso/YuE2-GGUF','mudler/locate-anything.cpp-gguf') else 8
  lease=Reservation(dict(run_id=key,profile=body.get('profile'),model=model,workload=body.get('prompt_id'),memory_limit_bytes=commit_gib*1024**3))
  try:lease.acquire()
  except AdmissionError as exc:
   row=dict(run_id=key,status='BLOCKED_BUSY',origin='ADMISSION_TEST',timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),model=body.get('model_id') or 'NOT_STARTED',profile=body.get('profile') or 'functional-admission',backend='NOT_STARTED',quantization='NOT_APPLICABLE',prompt_id=body.get('prompt_id','admission'),runtime_hash=None,artifacts=str(ROOT),comparison_key='INCOMPLETE:admission-v10',summary={},samples=[],events=[dict(kind='admission_rejected',detail=str(exc),at=time.time())],error=str(exc),cleanup=True,quality_gate='NOT_APPLICABLE')
   row['log_path']=str(ROOT/('admission-'+key+'.json'));row['finished_at']=row['timestamp'];row['execution_admission']=admission_status()
   write(Path(row['log_path']),row)
   workspace.store.put(row)
   if getattr(workspace,'lab',None) and workspace.lab.profile.get('publish_existing_benchmarks'):
    from serve.hydra_lab_integration import publish_existing_registry
    publish_existing_registry(workspace,Path(__file__).resolve().parents[1],run_id=key)
   return row
  try:
   kwargs['_key']=key
   features=getattr(getattr(workspace,'lab',None),'features',None)
   feature_resolution=None
   if features is not None:
    feature_resolution=features.begin(body)
    lease.row['request']['feature_version']=feature_resolution['version']
    lease.row['request']['feature_required']=feature_resolution['required']
    scheduling=next((v for k,v in feature_resolution['settings'].items() if k=='V7-F-034'),None)
    if scheduling and scheduling['desired']:
     from serve.hydra_cpu_scheduling import topology
     detected=topology()
     if not detected['available']:raise AdmissionError('ECORE_CAPABILITY: '+detected['reason'])
     lease.row['request']['cpu_affinity']=detected['ecores'][:2]
    lease.transition('PRECHECK')
   result=fn(workspace,body,*args,**kwargs)
   if feature_resolution is not None:result['feature_control']={k:feature_resolution[k] for k in ('version','required')}
   result['process_memory_policy']=lease.row.get('memory_policy')
   if lease.row['request'].get('cpu_affinity'):result['cpu_scheduling_policy']=dict(kind='VERIFIED_ECORE_PROCESS_AFFINITY',selected=lease.row['request']['cpu_affinity'],children=lease.row['children'])
   require_application_cleanup(result)
   if getattr(workspace,'lock',threading.Lock()).locked():raise AdmissionError('APPLICATION_CLEANUP_UNVERIFIED')
   if (Path(__file__).resolve().parents[1]/'data/.gpu-campaign.lock').exists():raise AdmissionError('APPLICATION_LEASE_UNRELEASED')
   lease.verify_cleanup()
   workspace.store.put(result)
   if getattr(workspace,'lab',None) and workspace.lab.profile.get('publish_existing_benchmarks'):
    from serve.hydra_lab_integration import publish_existing_registry
    publish_existing_registry(workspace,Path(__file__).resolve().parents[1],run_id=result['run_id'])
   if getattr(workspace,'lab',None):
    from serve.hydra_lab_live import retained
    retained(workspace)
   lease.release(persisted=bool(result and workspace.store.get(result['run_id'])))
   if features is not None:features.end()
   return result
  except Exception as exc:
   if body.get('profile')=='v21-bonsai-hybrid':
    notify_gpu_fault(body,str(exc),key)
   try:
    if getattr(workspace,'lock',threading.Lock()).locked() or (Path(__file__).resolve().parents[1]/'data/.gpu-campaign.lock').exists():raise AdmissionError('APPLICATION_CLEANUP_UNVERIFIED')
    try:previous=workspace.store.get(key)
    except (KeyError,ValueError):previous={}
    if previous.get('native_state_cleanup') is False:raise AdmissionError('APPLICATION_STATE_CLEANUP_UNVERIFIED')
    for component in ('transport_cleanup','process_cleanup','watcher_cleanup','runtime_ownership_cleanup','monitor_cleanup'):
     if previous.get(component) is False:raise AdmissionError('APPLICATION_'+component.upper()+'_UNVERIFIED; reservation retained')
    if previous.get('cleanup_errors'):raise AdmissionError('APPLICATION_CLEANUP_ERRORS; reservation retained')
    lease.verify_cleanup() # checks private Job, exact identities and spawn uncertainty
    try:row=workspace.store.get(key)
    except (KeyError,ValueError):
     stamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
     row=dict(run_id=key,origin='ADMISSION_TEST',timestamp=stamp,model=body.get('model_id') or 'NOT_STARTED',profile=body.get('profile') or 'functional-admission',backend='NOT_STARTED',quantization='NOT_APPLICABLE',prompt_id=body.get('prompt_id','admission'),runtime_hash=None,comparison_key='INCOMPLETE:admission-error',summary={},samples=[],events=[],quality_gate='NOT_APPLICABLE')
    row.update(status='BLOCKED_GPU_QUARANTINE' if 'GPU_QUARANTINED' in str(exc) or 'QUARANTINED' in str(exc) or 'suspended after native ErrorDeviceLost' in str(exc) else 'BLOCKED_FEATURE' if 'FEATURE_BLOCKED' in str(exc) else 'FAIL',error=type(exc).__name__+': '+str(exc),cleanup=True,finished_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),real_execution_kind='controlled software rejection; no completed inference')
    # A queued record exists before feature admission and has no comparison key.
    # Complete its reporting identity before publication, even when no child ran.
    row.setdefault('comparison_key','INCOMPLETE:admission-error')
    row.setdefault('summary',{})
    row.setdefault('samples',[])
    if body.get('feature_probe'):row['feature_ids']=[body['feature_probe']]
    folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True,exist_ok=True);log=folder/('coordinator-error-'+uuid.uuid4().hex+'.json');row.update(artifacts=str(folder),log_path=str(log));row.setdefault('events',[]).append(dict(at=row['finished_at'],kind='coordinator_rejection_after_verified_cleanup',detail=row['error']));write(log,row);workspace.store.put(row)
    if getattr(workspace,'lab',None) and workspace.lab.profile.get('publish_existing_benchmarks'):
     from serve.hydra_lab_integration import publish_existing_registry
     publish_existing_registry(workspace,Path(__file__).resolve().parents[1],run_id=key)
    lease.release(persisted=bool(workspace.store.get(key)))
    if getattr(getattr(workspace,'lab',None),'features',None) is not None:workspace.lab.features.end()
    return row
   except Exception:
    if body.get('profile')=='v21-bonsai-hybrid':
     notify_gpu_fault(body,str(exc),key)
    if body.get('profile') in ('v20-bonsai-hybrid-16','v20-bonsai-vulkan-full'):
     notify_gpu_fault(body,'CLEANUP_UNCERTAIN',key)
    lease.transition('CLEANUP_BLOCKED');raise
 return wrapped


def publication_row(row):
 lease=getattr(_local,'reservation',None)
 # A software metadata operation may republish an already terminal native run.
 # Its unrelated live lease must never replace that run's own attestation or
 # demote PASS to RUNNING. Missing IDs retain the conservative legacy behavior.
 if lease and row.get('run_id') is not None and row['run_id']!=lease.row['run_id']:return row
 if lease:
  lease.row['attested_request']={k:row[k] for k in ('model','model_hash','runtime','runtime_hash','profile','backend','configuration','parameters','prompt_id','prompt_hash') if k in row}
  kind=(row.get('events') or [{}])[-1].get('kind')
  state={'startup':'STARTING','loading':'STARTING','warmup_start':'WARMUP','request_start':'RUNNING','cleanup':'CLEANUP','cleanup_failed':'CLEANUP_BLOCKED'}.get(kind)
  if state and lease.row['state'] not in ('VERIFIED_TERMINAL','RELEASED'):lease.transition(state)
  row=dict(row,execution_admission={'run_id':lease.row['run_id'],'owner':lease.row['owner'],'state':lease.row['state'],'children':lease.row['children']})
 if lease and row.get('status')=='PASS' and lease.row['state']!='VERIFIED_TERMINAL':
  row=dict(row,pending_terminal_status='PASS',status='RUNNING',admission_state=lease.row['state'])
 return row

def admission_status():
 from serve.hydra_gpu_recovery_v16 import public_status
 from serve.hydra_acceptance_v18 import public_status as campaign_status
 from serve.hydra_acceptance_v19 import public_status as campaign19_status
 from serve.hydra_engine_v20 import public_status as v20_status
 from serve.hydra_engine_v21 import public_status as v21_status
 v21=v21_status();v20=v20_status();recovery=public_status();campaign=campaign_status();campaign['v19']=campaign19_status()
 try:
  row=json.loads((ROOT/'lease.json').read_text(encoding='utf8'))
  return dict(rejected_attempts=len(list(ROOT.glob('rejected-*.json'))),state=row['state'],run_id=row['run_id'],owner=row['owner'],children=row['children'],events=row['events'],request={k:v for k,v in row.get('request',{}).items() if k in ('feature_version','feature_required')},gpu='QUARANTINED' if (ROOT.parent/'hydra-v8-safety-stop.json').exists() else 'NOT_ATTESTED',gpu_recovery=recovery,gpu_acceptance_v18=campaign,gpu_v20=v20,gpu_v21=v21)
 except FileNotFoundError:return dict(state='IDLE',gpu='QUARANTINED' if (ROOT.parent/'hydra-v8-safety-stop.json').exists() else 'NOT_ATTESTED',gpu_recovery=recovery,gpu_acceptance_v18=campaign,gpu_v20=v20,gpu_v21=v21)
 except Exception:return dict(state='UNKNOWN',admission='BLOCKED')


def require_child_admission():
 try:
  lease=json.loads((ROOT/'lease.json').read_text(encoding='utf8'))
  current=identity()
  if lease['state'] not in ('STARTING','WARMUP','RUNNING') or not alive(lease['owner']):raise AdmissionError('NO_VALID_CHILD_RESERVATION')
  direct=any(c['pid']==current['pid'] and abs(c['created']-current['created'])<.01 for c in lease['children'])
  if not direct:
   if '--dense-worker' not in lease.get('expected_command',[]):raise AdmissionError('NO_VALID_CHILD_RESERVATION')
   parents=[dict(pid=p.pid,created=p.create_time()) for p in psutil.Process(current['pid']).parents()]
   if not any(p['pid']==c['pid'] and abs(p['created']-c['created'])<.01 for p in parents for c in lease['children']):raise AdmissionError('NO_VALID_CHILD_RESERVATION')
   write(ROOT/('child-admission-'+uuid.uuid4().hex+'.json'),dict(run_id=lease['run_id'],current=current,parents=parents,registered_children=lease['children'],kind='verified owned Python redirector descendant'))
 except (OSError,ValueError,KeyError,TypeError):raise AdmissionError('NO_VALID_CHILD_RESERVATION') from None
