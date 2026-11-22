"""Pure local preconditions shared by lab admission and workers.

Metadata compatibility is necessary, never runtime or hardware attestation.
No model file is opened, no network operation or process launch is performed.
"""
import copy, re, threading

class CapabilityError(ValueError):pass

BLOCKERS={
 'moe':'COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED',
 'weight_tiering':'PRISM_GRAPH_BUFFER_REBIND_API_REQUIRED',
 'speculative':'ATTESTED_DRAFT_TARGET_ADAPTER_REQUIRED',
 'remote':'AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED',
 'full35b':'FULL35B_RUNTIME_IDENTITY_AND_MEMORY_MANIFEST_REQUIRED',
 'expert_eviction':'REVOCABLE_GRAPH_SLOT_REFERENCES_REQUIRED',
}

def integer(value,minimum=0,maximum=2**63-1):
 if type(value) is not int or not minimum<=value<=maximum:raise CapabilityError('INVALID_INTEGER_OR_MEMORY_BOUND')
 return value

def digest(value):
 if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):raise CapabilityError('ARTIFACT_IDENTITY_REQUIRED')
 return value

def model_identity(value):
 if not isinstance(value,dict):raise CapabilityError('MODEL_MANIFEST_REQUIRED')
 row=copy.deepcopy(value)
 for key in ('sha256','runtime_sha256','tokenizer_sha256','vocabulary_sha256'):digest(row.get(key))
 if not isinstance(row.get('architecture'),str) or not row['architecture']:raise CapabilityError('ARCHITECTURE_REQUIRED')
 vocab=integer(row.get('vocab_size'),1);integer(row.get('context'),1)
 integer(row.get('bos'),0,vocab-1)
 if not isinstance(row.get('eos'),list) or not row['eos']:raise CapabilityError('EOS_REQUIRED')
 for token in row['eos']:integer(token,0,vocab-1)
 if row.get('sequence_format')!='tokens-v1':raise CapabilityError('SEQUENCE_FORMAT_UNSUPPORTED')
 return row

def speculative_contract(draft,target,draft_sequence,target_sequence,max_draft_tokens):
 draft=model_identity(draft);target=model_identity(target)
 if draft['sha256']==target['sha256']:raise CapabilityError('DRAFT_IS_TARGET_OR_IDENTICAL_BLOB')
 for key in ('tokenizer_sha256','vocabulary_sha256','vocab_size','bos','eos','sequence_format'):
  if draft[key]!=target[key]:raise CapabilityError('DRAFT_TARGET_MISMATCH: '+key)
 # Existing native dispatcher has no cross-architecture state adapter.
 if draft['architecture']!=target['architecture']:raise CapabilityError('DRAFT_TARGET_ARCHITECTURE_ADAPTER_REQUIRED')
 maximum=integer(max_draft_tokens,1,min(draft['context'],target['context']))
 if not isinstance(draft_sequence,list) or not isinstance(target_sequence,list) or draft_sequence!=target_sequence:raise CapabilityError('DRAFT_TARGET_SEQUENCE_MISMATCH')
 if not draft_sequence or len(draft_sequence)+maximum>min(draft['context'],target['context']):raise CapabilityError('DRAFT_TARGET_CONTEXT_BUDGET')
 for token in draft_sequence:integer(token,0,draft['vocab_size']-1)
 return dict(status='COMPATIBLE_METADATA_ONLY',draft=draft,target=target,max_draft_tokens=maximum,execution_enabled=False)

def full_model_budget(identity,components,limit_bytes,safety_margin_bytes):
 from serve.hydra_memory_budget import checked_sum
 identity=model_identity(identity);limit=integer(limit_bytes,1);margin=integer(safety_margin_bytes)
 keys={'weights','state','kv','workspace','runtime_buffers'}
 if not isinstance(components,dict) or set(components)!=keys:raise CapabilityError('COMPLETE_MEMORY_UPPER_BOUND_REQUIRED')
 sizes={key:integer(components[key],1) for key in keys}
 total=checked_sum([*sizes.values(),margin])
 if total>limit:raise CapabilityError('FULL_MODEL_MEMORY_BUDGET_EXCEEDED')
 return dict(status='COMPATIBLE_METADATA_ONLY',identity=identity,components=sizes,total_bytes=total,limit_bytes=limit,execution_enabled=False)

def moe_contract(backbone,pack,backend):
 model=model_identity(backbone)
 if not isinstance(pack,dict):raise CapabilityError('EXPERT_PACK_MANIFEST_REQUIRED')
 digest(pack.get('sha256'))
 if pack.get('backbone_sha256')!=model['sha256']:raise CapabilityError('EXPERT_BACKBONE_IDENTITY_MISMATCH')
 for key in ('n_expert','n_layers','hidden','ff'):
  value=integer(model.get(key),1,65535)
  if type(pack.get(key)) is not int or pack[key]!=value:raise CapabilityError('EXPERT_GEOMETRY_MISMATCH: '+key)
 for key in ('tokenizer_sha256','vocabulary_sha256','architecture'):
  if pack.get(key)!=model[key]:raise CapabilityError('EXPERT_MODEL_MISMATCH: '+key)
 if pack.get('format')!='planarQ2' or (model['hidden'],model['ff'],model['n_expert'])!=(2560,640,512):raise CapabilityError('EXPERT_DISPATCH_FORMAT_UNSUPPORTED')
 if backend not in ('cpu-planar-q2','cuda-planar-q2','hip-planar-q2'):raise CapabilityError('EXPERT_BACKEND_UNSUPPORTED')
 return dict(status='COMPATIBLE_METADATA_ONLY',backend=backend,execution_enabled=False,eviction_enabled=False,eviction_reason=BLOCKERS['expert_eviction'])

def remote_contract(node,task,timeout_seconds):
 from urllib.parse import urlsplit
 if not isinstance(node,dict) or not isinstance(task,dict):raise CapabilityError('REMOTE_IDENTITY_MANIFEST_REQUIRED')
 for key in ('authorization_sha256','runtime_sha256','model_sha256','tokenizer_sha256'):
  digest(node.get(key))
  if task.get(key)!=node[key]:raise CapabilityError('REMOTE_IDENTITY_MISMATCH: '+key)
 if not isinstance(node.get('node_id'),str) or not node['node_id'] or node['node_id']!=task.get('node_id'):raise CapabilityError('REMOTE_NODE_IDENTITY_MISMATCH')
 endpoint=urlsplit(node.get('endpoint',''))
 if endpoint.scheme!='https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ('','/'):raise CapabilityError('REMOTE_ISOLATED_ENDPOINT_REQUIRED')
 digest(node.get('tls_certificate_sha256'))
 timeout=integer(timeout_seconds,1,60)
 if not isinstance(task.get('request_id'),str) or not 1<=len(task['request_id'])<=128:raise CapabilityError('REMOTE_REQUEST_ID_REQUIRED')
 return dict(status='COMPATIBLE_METADATA_ONLY',node_id=node['node_id'],request_id=task['request_id'],timeout_seconds=timeout,execution_enabled=False,cancellation='Requires owned remote acknowledgement before releasing node lease; local close is not proof of remote cancellation')

def guard_request(body):
 if not isinstance(body,dict):raise CapabilityError('REQUEST_OBJECT_REQUIRED')
 # Optional capabilities may never pass through as ignored request fields.
 sources=[body]
 if isinstance(body.get('request'),dict):sources.append(body['request'])
 for source in sources:
  for key in ('moe','expert_cache','expert_eviction','weight_tiering','speculative','draft_model','remote','remote_node','full35b'):
   if source.get(key) not in (None,False):
    value=source[key]
    if isinstance(value,dict):
     if key=='moe' and value.get('native_target')=='hf_85a248b2_q2_0':
      from pathlib import Path
      target=native_moe_target(Path(__file__).resolve().parents[1])
      raise CapabilityError(target['dependency'])
     if key=='moe':moe_contract(value.get('backbone'),value.get('pack'),value.get('backend'))
     elif key=='speculative':speculative_contract(value.get('draft'),value.get('target'),value.get('draft_sequence'),value.get('target_sequence'),value.get('max_draft_tokens'))
     elif key=='full35b':full_model_budget(value.get('identity'),value.get('components'),value.get('limit_bytes'),value.get('safety_margin_bytes'))
     elif key=='remote' and 'node' in value:remote_contract(value.get('node'),value.get('task'),value.get('timeout_seconds'))
    family={'expert_cache':'moe','draft_model':'speculative','remote_node':'remote','full35b':'full35b'}.get(key,key)
    raise CapabilityError(BLOCKERS[family])
  labels=[str(source.get(key,'')).lower() for key in ('model_id','model','profile')]
  if any('colibri' in label and ('35b' in label or 'full' in label) for label in labels):raise CapabilityError(BLOCKERS['full35b'])
  if any('hf_85a248b2_q2_0' in label for label in labels):
   from pathlib import Path
   from serve.hydra_native_admission import require_native_moe
   require_native_moe(Path(__file__).resolve().parents[1])
 return []

def native_moe_target(root):
 """Inspect existing native Strata configuration, without opening any weights.

 Presence and structural metadata do not attest weight identity or admit GPU
 execution. This inventory is also consumed by the existing feature resolver.
 """
 import hashlib,json
 from pathlib import Path
 from serve.hydra_native_admission import project_path
 root=Path(root).resolve();config=project_path(root/'strata-hf_85a248b2_q2_0.json',root.parent)
 if not config.is_file() or config.stat().st_size>65536:raise CapabilityError('NATIVE_MOE_CONFIG_REQUIRED')
 raw=config.read_bytes();record=json.loads(raw);args=record.get('args',[])
 if not isinstance(args,list) or not all(isinstance(v,str) for v in args):raise CapabilityError('NATIVE_MOE_ARGUMENT_MANIFEST_INVALID')
 def argument(name):
  if args.count(name)!=1 or args.index(name)+1>=len(args):raise CapabilityError('NATIVE_MOE_ARGUMENT_REQUIRED: '+name)
  from serve.hydra_native_admission import project_path
  p=project_path(args[args.index(name)+1],root.parent)
  if not p.is_relative_to(root.parent):raise CapabilityError('NATIVE_MOE_ASSET_OUTSIDE_PROJECT')
  return p
 pack=argument('--pack');weights=[argument('--native'),argument('--ple-gguf')]
 from serve.hydra_native_admission import project_path,native_preflight
 tokenizer=project_path(record.get('tokenizer',''),root.parent);runtime=project_path(record.get('exe',''),root.parent)
 if not tokenizer.is_relative_to(pack) or not runtime.is_relative_to(root):raise CapabilityError('NATIVE_MOE_RUNTIME_TOKENIZER_SCOPE')
 files=[config,pack/'index.txt',pack/'native_experts.txt']+[tokenizer/name for name in ('tokenizer.json','vocab.json','merges.txt','chat_template.jinja')]
 if not project_path(pack/'dense.bin',root.parent).is_file() or any(not p.is_file() for p in weights+[runtime]):raise CapabilityError('NATIVE_MOE_ASSETS_REQUIRED')
 for p in files:
  if p.is_symlink() or not p.is_file() or p.stat().st_size>16*1024**2:raise CapabilityError('NATIVE_MOE_METADATA_INVALID')
 layout=(pack/'native_experts.txt').read_text().splitlines();rows=[line.split() for line in layout if line.strip() and not line.startswith('#')]
 if not rows or [int(row[0]) for row in rows]!=list(range(len(rows))) or any(len(row)<8 for row in rows):raise CapabilityError('NATIVE_MOE_LAYER_LAYOUT_INVALID')
 # Type42 is already implemented by the real native dispatcher; do not reinterpret
 # an arbitrary pack as planarQ2, or infer the backbone from tokenizer.pre.
 if any(int(row[1])!=42 or int(row[2])!=42 or int(row[4])<=0 for row in rows):raise CapabilityError('NATIVE_MOE_LAYOUT_REQUIRES_DIFFERENT_DISPATCH')
 admission=native_preflight(root)
 return dict(target='hf_85a248b2_q2_0',native_config_present=True,structural_metadata_present=True,layers=len(rows),native_types=[42],backend=record.get('backend'),runtime=str(runtime),weights=[dict(path=str(p),bytes=p.stat().st_size) for p in weights],metadata_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},weights_opened=False,execution_enabled=False,admission_v26=admission,dependency=admission['dependency'],scope='Existing native engine and pack found; no tensor/model parsing, weight attestation, load or GPU admission inferred')

class RuntimeOwnership:
 """Owns the whole native process; selective tensor unload remains unavailable.

 A process exit proves its graph/alias consumers stopped. It does not prove that
 a live runtime can unbind individual weights. Only the former is used here.
 """
 def __init__(self,session,model_sha256):
  digest(model_sha256)
  if not isinstance(session,str) or not session:raise CapabilityError('SESSION_IDENTITY_REQUIRED')
  self.session=session;self.model_sha256=model_sha256;self.state='CREATED';self.child=None;self.inflight=0;self.lock=threading.RLock()
 def attach(self,child):
  with self.lock:
   if self.state!='CREATED' or child.poll() is not None:raise CapabilityError('RUNTIME_ATTACH_INVALID')
   self.child=child;self.state='BOUND'
 def begin_sequence(self):
  with self.lock:
   if self.state!='BOUND' or self.inflight or self.child.poll() is not None:raise CapabilityError('RUNTIME_SEQUENCE_BUSY_OR_CLOSED')
   self.inflight=1;self.state='IN_FLIGHT'
 def end_sequence(self):
  with self.lock:
   if self.state!='IN_FLIGHT':raise CapabilityError('RUNTIME_SEQUENCE_TRANSITION')
   self.inflight=0;self.state='BOUND'
 def unload_weights(self):raise CapabilityError(BLOCKERS['weight_tiering'])
 def close(self):
  with self.lock:
   if self.state=='CLOSED':return
   if self.child is not None and self.child.poll() is None:raise CapabilityError('RUNTIME_CONSUMERS_STILL_LIVE')
   self.inflight=0;self.state='CLOSED'
 def snapshot(self):
  with self.lock:return dict(session=self.session,model_sha256=self.model_sha256,state=self.state,inflight=self.inflight,weight_tiering=False,weight_tiering_reason=BLOCKERS['weight_tiering'])
