"""Bounded native slot persistence; a session-local state transfer, never weight tiering."""
import hashlib,json,shutil,threading
from pathlib import Path

def frozen_detail(value):
 import copy
 return copy.deepcopy(value)

def continuation_messages(messages,output,followup):
 if not output.strip() or not isinstance(followup,str) or not 1<=len(followup)<=200:raise ValueError('NATIVE_STATE_CONTINUATION_REQUIRED')
 return frozen_detail(messages)+[dict(role='assistant',content=output),dict(role='user',content=followup)]

def state_size_bound(lines):
 import math,re
 values=[float(m[1]) for line in lines if ('KV buffer size' in line or 'RS buffer size' in line) and (m:=re.search(r'size\s*=\s*([0-9.]+) MiB',line))]
 if not values:raise ValueError('NATIVE_STATE_SIZE_UNKNOWN')
 return math.ceil(sum(values)*1024**2)+4*1024**2

def native_cached_tokens(response,prompt_tokens,saved_tokens):
 try:count=response['usage']['prompt_tokens_details']['cached_tokens']
 except (KeyError,TypeError):raise ValueError('NATIVE_CACHED_TOKEN_EVIDENCE_MISSING') from None
 if type(count) is not int or type(prompt_tokens) is not int or type(saved_tokens) is not int or not 0<=count<=min(prompt_tokens,saved_tokens):raise ValueError('NATIVE_CACHED_TOKEN_EVIDENCE_INVALID')
 return count

def session_identity(model,runtime,session,context,layers,thinking,options):
 from serve.hydra_capability_contracts import digest,integer
 digest(model);digest(runtime);integer(context,1);integer(layers,0,65535)
 if not isinstance(session,str) or not session or thinking not in ('on','off'):raise ValueError('NATIVE_SESSION_IDENTITY_REQUIRED')
 # These GGUF adapters embed tokenizer and template in the model asset. The
 # model hash therefore binds them; it is not an independent tokenizer probe.
 return dict(model=model,runtime=runtime,session=session,context=context,layers=layers,thinking=thinking,slot_id=0,embedded_tokenizer_model_sha256=model,options=frozen_detail(options))

class NativeSlot:
 def __init__(self,root,identity,budget):
  if type(budget) is not int or not 1<=budget<=512*1024**2:raise ValueError('NATIVE_STATE_BUDGET')
  self.root=Path(root);self.root.mkdir(exist_ok=False);self.identity=frozen_detail(identity);self.budget=budget;self.meta=None;self.state='CREATED';self.lock=threading.RLock()
  stat=self.root.stat();self.root_key=(stat.st_dev,stat.st_ino)
 def owned_root(self):
  if self.root.is_symlink() or self.root.is_junction():return False
  try:stat=self.root.stat()
  except OSError:return False
  return self.root_key==(stat.st_dev,stat.st_ino)
 def verify(self):
  with self.lock:
   try:self._verify()
   except BaseException:
    if self.state!='CLOSED':self.state='FAILED'
    raise
 def _verify(self):
  p=self.root/'state.bin'
  sidecar=self.root/'identity.json'
  if self.state in ('CLOSED','FAILED') or not self.owned_root() or p.is_symlink() or sidecar.is_symlink() or not self.meta or self.meta['identity']!=self.identity or not p.is_file() or p.stat().st_size!=self.meta['bytes'] or p.stat().st_size>self.budget:raise ValueError('NATIVE_STATE_IDENTITY_OR_SIZE')
  if not sidecar.is_file() or sidecar.stat().st_size>16384 or json.loads(sidecar.read_text(encoding='utf8'))!=self.meta:raise ValueError('NATIVE_STATE_SIDECAR_CHANGED')
  with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
  if h!=self.meta['sha256']:raise ValueError('NATIVE_STATE_HASH_MISMATCH')
 def cycle(self,api,cancel=None,expected_bound=None,destination_identity=None):
  if not self.lock.acquire(False):raise ValueError('NATIVE_STATE_BUSY')
  try:
   if self.state!='CREATED':raise ValueError('NATIVE_STATE_INVALID_TRANSITION: '+self.state)
   if not self.owned_root():raise ValueError('NATIVE_STATE_UNOWNED_ROOT')
   if destination_identity is not None and destination_identity!=self.identity:raise ValueError('NATIVE_STATE_DESTINATION_MISMATCH')
   return self._cycle(api,cancel,expected_bound)
  except BaseException:
   if self.state!='CLOSED':self.state='FAILED'
   raise
  finally:self.lock.release()
 def _cycle(self,api,cancel,expected_bound):
  if expected_bound is not None and (type(expected_bound) is not int or not 1<=expected_bound<=self.budget):raise ValueError('NATIVE_STATE_BUDGET_BEFORE_SAVE')
  if cancel and cancel.is_set():raise ValueError('NATIVE_STATE_CANCELLED')
  if shutil.disk_usage(self.root).free<self.budget+1024**3:raise ValueError('NATIVE_STATE_DISK_MARGIN')
  saved=api('save',{'filename':'state.bin'});p=self.root/'state.bin'
  if p.is_symlink() or not p.is_file():raise ValueError('NATIVE_STATE_UNOWNED_PAYLOAD')
  size=p.stat().st_size
  if not 0<size<=self.budget or type(saved.get('n_written')) is not int or type(saved.get('n_saved')) is not int or saved['n_written']!=size or saved['n_saved']<1:raise ValueError('NATIVE_STATE_BUDGET_OR_NATIVE_SIZE')
  if 'context' in self.identity and (type(self.identity['context']) is not int or not 1<=saved['n_saved']<=self.identity['context']):raise ValueError('NATIVE_STATE_POSITION_OUTSIDE_CONTEXT')
  with p.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
  self.meta=dict(identity=frozen_detail(self.identity),bytes=size,sha256=h,saved_tokens=saved['n_saved']);self.state='SAVED'
  (self.root/'identity.json').write_text(json.dumps(self.meta,indent=2),encoding='utf8');self.verify()
  if cancel and cancel.is_set():raise ValueError('NATIVE_STATE_CANCELLED')
  erased=api('erase',{});self.verify()
  if type(erased.get('n_erased')) is not int or erased['n_erased']!=saved['n_saved']:raise ValueError('NATIVE_STATE_ERASE_MISMATCH')
  self.state='ERASED'
  if cancel and cancel.is_set():raise ValueError('NATIVE_STATE_CANCELLED')
  restored=api('restore',{'filename':'state.bin'})
  if type(restored.get('n_read')) is not int or type(restored.get('n_restored')) is not int or restored['n_read']!=size or restored['n_restored']!=saved['n_saved']:raise ValueError('NATIVE_STATE_RESTORE_MISMATCH')
  self.verify()
  if cancel and cancel.is_set():raise ValueError('NATIVE_STATE_CANCELLED_AFTER_RESTORE')
  self.state='RESTORED'
  return dict(self.meta,lifecycle=self.state,budget_bytes=self.budget,restored_tokens=restored['n_restored'],native_save=saved,native_erase=erased,native_restore=restored,scope='Actual native sequence state transferred through disk; RAM residency and model-weight eviction not inferred')
 def close(self):
  with self.lock:
   if self.state=='CLOSED':return
   if not self.owned_root():raise OSError('NATIVE_STATE_UNOWNED_ROOT; cleanup refused')
   for name in ('state.bin','identity.json'):(self.root/name).unlink(missing_ok=True)
   self.root.rmdir();self.state='CLOSED'
