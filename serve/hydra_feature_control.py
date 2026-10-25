"""Versioned LAB policy, shared by the control UI and admitted execution.

ACTIVE means applied/available for a future request, never a loaded model.
No method in this module launches a process or contacts a provider.
"""
import copy,hashlib,json,sqlite3,time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone

class FeatureError(ValueError):pass
SCHEMA=1
H=Path(__file__).resolve().parents[1]/'hydra-engine'
MANDATORY={4,5,10,12,18,19,25,27,37,47,48,49,50,52,55,56}
SUPPORTED={1,2,3,6,7,9,11,13,14,17,20,21,22,23,24,26,28,29,34,35,38,39,40,41,43,44,45,53,54}
DEPENDENCIES={3:[1],13:[14],14:[39],17:[26],20:[1],21:[20],22:[21],23:[20],26:[20],29:[1],34:[1],35:[1],38:[1],39:[1],40:[1],41:[1],43:[1],44:[45],45:[39]}
DEFAULT_ON={1,24,28,38,53,54}|MANDATORY
PARAMETERS={
 16:{'max_checkpoint_mib':('int',1,512,384)},
 29:{'loader_mode':('int',0,1,0)},
 13:{'checkpoint_tier':('int',0,1,0)},
 9:{'threads':('int',1,2,2),'affinity_cpus':('int',1,2,2)},
 11:{'context':('int',512,2048,2048),'max_tokens':('int',1,128,128),'seed':('int',0,2147483647,42)},
 17:{'resident_tier':('int',0,2,2)},
 14:{'max_checkpoint_mib':('int',1,64,16)},
 20:{'max_nodes':('int',1,2,2)},24:{'min_query_chars':('int',1,200,40)},
}
BLOCKS={
 2:('QUARANTINED','Partial/full GPU offload and device selection require the separate GPU recovery gate.'),
 7:('QUARANTINED','Flash Attention requires an explicit finite v18/v19 campaign and its specific ON control; historical GPU profiles remain quarantined.'),
 8:('QUARANTINED','Prism batch/ubatch experiments require quarantined Vulkan path; historical NO_GO retained.'),
 15:('QUARANTINED','Native hit/miss dispatch exists in expert_hit_run and calls moe_hit_grouped_s2, including current activation quantization and destination slots. Compatible native pack is not admitted; GPU quarantine prevents cache execution/parity. CPU fallback is a separate path.'),
 16:('QUARANTINED','V18 GPU repeated-prefix runs report 453 native cache tokens reused with identical output/token IDs and GPU KV buffers; checkpoint/restore and native ExpertCache dispatch remain unverified. This control does not authorize those operations.'),
 29:('BLOCKED','IOCP helper verified on synthetic files; not connected to this model loader. Cannot claim model I/O activation.'),
 30:('UNSUPPORTED','Linux-only O_DIRECT/io_uring; Windows environment.'),
 31:('BLOCKED','Expert prefetch/streaming needs native expert path and a separately admitted large pack.'),
 32:('BLOCKED','No admitted draft/target pair and application adapter.'),
 33:('QUARANTINED','GPU graph capture/secondary accelerators not admitted.'),
 36:('BLOCKED','Remote pipeline requires explicit dedicated-node authorization; production Ubuntu excluded.'),
 42:('QUARANTINED','Image adapter executes Vulkan diffusion even with CPU weight placement.'),
 46:('BLOCKED','Full35B model memory upper bound/admission and installed-runtime source/tokenizer identity remain unverified. Separate pinned-source tokenizer-only probe completed12 cases under128 MiB commit cap (7 preserved,5 changed boundaries); it does not admit model loading or attest installed/live parity.'),
 51:('UNSUPPORTED','Routing/planner research variants are software-only; no new runtime dispatcher.'),
}

def stamp():return datetime.now(timezone.utc).isoformat()
def feature_number(fid):
 try:return int(fid.rsplit('-',1)[1]) if fid.startswith('V7-') else None
 except ValueError:return None
def adapter_id(model):return 'adapter.'+model

def definitions(catalog):
 matrix=H/'experimental_validation_v7_20261018_095534/feature-matrix.json'
 original=json.loads(matrix.read_text(encoding='utf8'));ids={feature_number(r['feature_id']):r['feature_id'] for r in original};out={}
 for item in original:
  fid=item['feature_id'];n=feature_number(fid);mandatory=n in MANDATORY;kind='mandatory' if mandatory else 'switch' if n in SUPPORTED else 'request_only'
  out[fid]=dict(id=fid,name=item['name'],description=item.get('evidence',''),category=item['area'],module=item['code_path'],runner='serve.hydra_lab_functional / Workspace.execute' if kind=='switch' else item['code_path'],provider='source-linked v11 laboratory implementation',entry_point='shared admitted lab resolver' if kind=='switch' else 'inspection / blocked activation request',experimental=n not in MANDATORY|{1,38,52,53,54,55,56},backend='GPU' if n in (7,8,16,33,42) else 'CPU_OR_SOFTWARE',control=kind,dependencies=[ids[v] for v in DEPENDENCIES.get(n,[])],incompatibilities=[],profiles=['HYDRA_LAB_MODE=1'],parameters_schema={k:dict(type=v[0],min=v[1],max=v[2],default=v[3]) for k,v in PARAMETERS.get(n,{}).items()},default_desired=n in DEFAULT_ON,build_status='SOURCE_PRESENT; see v11 target manifest',verification={'historical':item['result'],'kind':item['evidence_kind'],'evidence':item['artifacts']},prerequisites=['Exclusive coordinator and verified cleanup','Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail'],rollback='Save OFF or restore an earlier configuration revision; no history deletion',parameter_scope='Qwen CPU functional path' if n in (6,9,11,28) else 'Graph path' if n in (20,24) else 'No configurable runtime parameters',blocked=BLOCKS.get(n),evidence_runs=[])
  if n==1:out[fid].update(name='Backend CPU',description='Historical CPU/Vulkan group reconciled: this control gates CPU; GPU backends have separate quarantined controls.')
  if n==29:out[fid].update(name='Loader modello Windows IOCP',description='Qwen CPU laboratory only: IOCP delivers actual tensor bytes to llama_file::read_raw in the attested isolated CPU runtime. OFF uses the original reference runtime. Requires mmap OFF; no silent fallback or speedup claim. Applies to new requests after owned cleanup.',module='src/platform/direct_file.cpp + include/hydra/platform/model_reader.hpp',entry_point='Lab.start -> candidate llama_file::read_raw',blocked=None if (H/'runtime_integration_v14/loader-runtime-manifest.json').is_file() or (H/'engine_completion_v22/qwen-loader-manifest.json').is_file() else ('BLOCKED','Isolated IOCP CPU runtime not built/attested; no fallback'),parameter_scope='Qwen CPU only; other native adapters explicitly refused while requested')
  if n==29:out[fid].update(description=out[fid]['description']+' Bonsai PTQ1_0 CPU uses its separate source-pinned Prism IOCP candidate when its v20 manifest exists; missing candidate fails without fallback. GPU Prism remains standard only.',parameter_scope='Qwen CPU and manifest-attested Bonsai CPU; mmap OFF; loader_mode0=IOCP,1=candidate standard; OFF restores each model reference binary')
  if n==13:out[fid].update(description='Request-local exact native CPU prefix checkpoint. checkpoint_tier:0=RAM reference,1=exclusive temporary disk file with exact-byte integrity check and reload before native restore. Disk mode releases retained checkpoint allocation between alternatives. Not weight tiering or cross-request cache.',parameter_scope='checkpoint_tier0/1; OFF uses no checkpoint or file; budget controlled by feature14',module='serve/hydra_scoring_runtime.py + hydra_lab/checkpoint_tier.hpp')
  if n==29:out[fid].update(description=out[fid]['description']+' loader_mode:0=IOCP,1=standard reads in the same isolated CPU candidate; both require mmap OFF. Candidate instrumentation is not a speedup claim.',parameter_scope='loader_mode0/1; OFF restores reference binary and loader')
  if n in (15,16,26,29,35):out[fid]['implementation_v22']=dict(level='IMPLEMENTATION_AND_SOFTWARE_CONTRACTS; no new native model execution',modules={15:'ExpertLayout checked offsets + ExpertPool host batch ownership',16:'NativeSlot lifecycle/sidecar/erase/restore/cleanup',26:'Graphify selected bytes revalidated around ingestion and compiler',29:'Separate rebuilt CPU IOCP loaders; owner-thread drain',35:'Lab and native adapters use the same revocable serial HTTP pool'}[n])
  if n==29:out[fid].update(description=out[fid]['description']+' V22 prefers source-attested rebuilt CPU candidates for Qwen and Bonsai; changed helper identities fail closed. Rebuild and software checks are not model-loading validation.',build_status='V22_CPU_BUILDS_NO_MODEL_EXECUTION' if (H/'engine_completion_v22/prism-loader-manifest.json').is_file() and (H/'engine_completion_v22/qwen-loader-manifest.json').is_file() else out[fid]['build_status'])
  if n==35:out[fid].update(entry_point='Lab.start and native template server; serial HTTP only',description='ON attaches one owned HTTP pool to supported local HTTP adapters; OFF preserves ordinary per-request connections. Timeout updates the live socket; released/cancelled leases cannot reconnect. Cleanup closes pool before backend release. No transport speedup or remote-generation claim.')
  if n==3:out[fid].update(name='Riuso runtime nel benchmark CPU',description='Qwen CPU normal runner:ON keeps one owned runtime across warmup/samples;OFF closes it after each request and reloads serially. Lock remains held through final cleanup. No resident model across independent admissions.',module='serve/hydra_lab_benchmarks.py',provider='Lab.start/stop_backend',entry_point='Qwen CPU benchmark; native template server with explicit samples1/2',parameter_scope='Within one admission; native samples2 requires ON and reuses one process, without warmup generation. OFF rejects samples2. Not cross-admission persistence.')
  capability_requirements={
   15:('BLOCKED','EXPERT_MODEL_INCOMPATIBLE: Bonsai qwen35 has n_expert=0. Local MTP expert pack H2560/FF640/512 experts is not its backbone. Native ExpertDispatch lookup/fill/grouped/output exists for admitted planarQ2 MoE only; no compatible complete backbone/tokenizer/device runtime admitted.'),
   31:('BLOCKED','WEIGHT_TIERING_UNSUPPORTED: Prism binds model tensors to long-lived backend buffers for its inference graph; no runtime weight unbind/reload hook. IOCP loads tensor bytes; native slot staging transfers sequence state only. Expert prefetch requires the separate compatible MoE pack and runtime.'),
   32:('BLOCKED','DRAFT_TARGET_INCOMPATIBLE: two local MTP expert blobs have the same SHA256 and belong to a separate H2560 expert layout; no admitted Bonsai qwen35 draft/tokenizer/runtime pair. Identical blobs are not a draft model.'),
   36:('BLOCKED','DEDICATED_NODE_REQUIRED: native RemoteExperts/PeerExperts transport remains source-linked; no authorized remote address, model/pack identity or remote device admission. Localhost software transport does not authorize distributed generation. Production Ubuntu excluded.'),
   46:('BLOCKED','COLIBRI_NOT_ADMITTED: require exact installed-runtime/tokenizer parity, full35B asset identity and model-plus-state/workspace memory upper bound. Tokenizer-only probe and smaller task outputs do not authorize the full model.')}
  if n in capability_requirements:out[fid].update(blocked=capability_requirements[n],prerequisites=out[fid]['prerequisites']+[capability_requirements[n][1]],capability_scope='Explicit runtime/model prerequisite; native component evidence is not complete LLM generation')
  if n==16:out[fid].update(name='Stato nativo Bonsai',module='serve/hydra_native_state.py + serve/hydra_native_text_server.py',provider='Prism native slot save/erase/restore',blocked=None,control='switch',description='Prism v21 session-local native slot save/erase/restore with model/runtime/session identity, SHA256, disk budget, cancellation and cleanup. CPU continuation restored158337104 bytes and reused22 tokens. GPU also requires a finite grant: native state transfer succeeded but repeated-prefix reuse was0; that mode is refused. Not weight tiering.',parameter_scope='max_checkpoint_mib1..512; explicit continuation checkpoint only; OFF denies new state operations; identity is request-local; no cross-session import')
  if n==6:out[fid].update(entry_point='Qwen and native template server requests',parameter_scope='cache_prompt passed to native inference; reuse across two native samples requires runtime reuse ON; no disk/KV checkpoint claim')
  if n==54:out[fid].update(name='Grafici delle prestazioni',description='Controls optional charts in the existing page. Safety controls and history remain available.')
  if n==26:out[fid].update(name='Graphify — contesto dal repository',description='Selects current local repository sources for Graph retrieval and Context Compiler; validates source identity and freshness. No GPU/weight acceleration.',module='serve/hydra_graphify_runtime.py',provider='Graphify AST candidates + current local source bytes',entry_point='/lab/benchmarks/functional; graph chat or retrieval')
  if n==26:
   archive=Path(__file__).resolve().parents[1]/'graphify-out/graph.json'
   if not archive.is_file():out[fid]['blocked']=('BLOCKED','Missing local repository graph: '+str(archive))
   elif archive.stat().st_size>40*1024**2:out[fid]['blocked']=('BLOCKED','Repository graph exceeds40 MiB source-selection budget')
  if n==17:out[fid].update(name='Tiering indice Graphify',description='Owns repository index data only:0 cold/source disk,1 warm/compressed RAM,2 hot/parsed RAM. Source archive re-read and hashed every request. Not model-weight tiering.',module='serve/hydra_graphify_runtime.py',provider='GraphIndexTiers',entry_point='Graphify retrieval/context',parameter_scope='Repository index residency only; not weights, KV or physical RAM')
  if n in (13,14):out[fid].update(name='Checkpoint prefisso scorer CPU' if n==13 else 'Budget checkpoint scorer CPU',description='Owns a bounded request-local native CPU full-state checkpoint for exact prefix reuse across alternatives. Cache OFF re-evaluates prefixes. Not GPU KV, cross-request conversation storage or Colibri state.',module='serve/hydra_scoring_runtime.py',provider='native-score-v13 + llama_state_get_data/set_data',entry_point='CPU score, exact prefix and isolated question bridge',parameter_scope='Checkpoint payload only; original native ConversationCache is a separate engine component')
  if n==13:out[fid].update(description='Request-local native CPU prefix state:checkpoint_tier0=RAM,1=temporary disk file. Disk mode releases retained allocation and restores exact bytes before llama_state_set_data. Exclusive file, checksum, budget and deletion on child exit; no fallback. Not model-weight tiering or cross-request cache.',parameter_scope='checkpoint_tier0/1; OFF creates no checkpoint; memory budget feature14',provider='native-score-v13 RAM / native-score-v14 disk; native full-state CPU API')
  if n==18:out[fid].update(name='Limite commit Windows obbligatorio',description='Windows process and aggregate Job commit limits:8 GiB for small-model/functional paths,24 GiB for native families. Flags and limits read back before suspended child assignment/resume. Not an RSS or physical-RAM cap; historical peak-accounting discrepancy retained.',module='serve/hydra_execution_v10.py',provider='Windows Job Object PROCESS_MEMORY + JOB_MEMORY',entry_point='Every exclusive_execute admission',verification={'kind':'DUMMY_CPU_COMMIT_REFUSAL_AND_REAL_CPU_REQUEST','evidence':str(H/'implementation_closure_v13/memory-cap-proof.json')})
  if n==34:
   from serve.hydra_cpu_scheduling import topology
   detected=topology();out[fid].update(name='Affinità E-core verificata',description='Selects up to two allowed group0 E-cores using Windows efficiency classes. Applies and reads back process affinity before child resume. OFF preserves normal adapter affinity; no speedup claimed.',module='serve/hydra_cpu_scheduling.py + serve/hydra_execution_v10.py',provider='Windows CPU-set information + process affinity',entry_point='shared admitted child creation',prerequisites=['Distinct Windows CPU efficiency classes; allowed group0 E-cores'],cpu_topology=detected)
   if not detected['available']:out[fid]['blocked']=('BLOCKED',detected['reason'])
  if n==35:out[fid].update(name='Riuso HTTP server testuale CPU',description='One connection and one in-flight request per native template-aware CPU server. Only fully consumed JSON responses reused; partial/SSE connections discarded. No automatic retry. Connections close at runtime cleanup.',module='serve/hydra_http_pool.py',provider='SerialConnectionPool',entry_point='native template-aware CPU adapter; explicit thinking on/off',parameter_scope='Bonsai/Huihui/NVFP4 template server only. Qwen HYDRA SSE, scoring C API and TTS retain their existing transports.')
  if n==44:out[fid].update(name='Bridge domande isolato CPU',description='System One-shaped noul/choice/score requests executed by HYDRA native Qwen CPU scoring. Explicit tokenizer/model provenance. No System One contact, Colibri boundary or semantic parity claim; pinned cache unsupported.',module='serve/hydra_system_one_bridge.py',provider='native CPU continuation scorer + bounded question formatter',entry_point='/lab/benchmarks/functional path=/lab/system-one-bridge',parameter_scope='1..4 questions,2..4 alternatives each; no operational System One changes')
  if n==45:out[fid].update(name='Scoring CPU con prefisso esatto',description='Native Qwen C API scoring of exact UTF8 prefix plus ordered continuations. No strip, NFC or implicit template. Actual token boundary checked; incompatible continuations return unscorable_boundary. Original fixture-only contract retained separately.',module='serve/hydra_prefix_scoring.py',provider='NativeCPUBackend + existing native_score helper',entry_point='/lab/benchmarks/functional path=/lab/score-prefix',parameter_scope='prefix<=128 native tokens; full sequence<=256 tokens;1..4 alternatives; no Colibri parity')
 for backend,reason in [('vulkan','ErrorDeviceLost cause UNKNOWN; GPU quarantine'),('hip','HIP compiled, GPU inference not admitted'),('cuda','CUDA toolkit nvcc unavailable; GPU quarantine')]:
  fid='runtime.'+backend;out[fid]=dict(id=fid,name='Backend '+backend.upper(),description=reason,category='A',module='serve/hydra_execution_v10.py',runner='Workspace.execute',provider=backend,entry_point='quarantined GPU admission',experimental=True,backend='GPU',control='request_only',dependencies=[],incompatibilities=[],profiles=['GPU historical profiles; not executable'],parameters_schema={},default_desired=False,build_status='COMPILED_NOT_EXECUTED' if backend=='hip' else 'RUNTIME_HISTORICAL' if backend=='vulkan' else 'TOOLCHAIN_MISSING',verification={'kind':'NO_NEW_GPU_EXECUTION'},prerequisites=['Distinct authorized GPU recovery gate'],rollback='OFF',parameter_scope='No GPU parameters applied while quarantined',blocked=('QUARANTINED',reason),evidence_runs=[])
 from serve.hydra_gpu_recovery_v16 import verified_gpu_evidence
 gpu_proof=verified_gpu_evidence()
 if gpu_proof['request_count']:
  out['runtime.vulkan'].update(build_status='BOUNDED_GPU_INFERENCE_VERIFIED',verification=dict(kind='REAL_GPU_GENERATION',**gpu_proof),evidence_runs=gpu_proof['run_ids'],profiles=['v8-recovery-qwen; explicit finite ticket only'],description='Generazione Vulkan AMD verificata sul piccolo Qwen. Accesso sperimentale opt-in; la quarantena storica resta distinta.',parameter_scope=gpu_proof['scope'],blocked=('QUARANTINED','Nuove richieste richiedono GPU ON e un ticket esplicito distinto. Inferenze precedenti verificate; causa del fault storico UNKNOWN.'))
 for model in catalog:
  fid=adapter_id(model['id']);task=model.get('lab_task');family=40 if model['id'].startswith('audio-cpp/') else 41 if model['id'].startswith('mudler/') else 43 if task=='music' or 'YuE2' in model['id'] else 42 if task=='image' or 'Image' in model['id'] else 38
  supported=model['id'] in ('local/Qwen3-0.6B-Q8_0','prism-ml/Ternary-Bonsai-2-27B-gguf','audio-cpp/audio.cpp-gguf','mudler/locate-anything.cpp-gguf','Serveurperso/YuE2-GGUF','huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF','cdiamond/Qwen3.8-27B-iMatrix-NVFP4-MTP-GGUF')
  blocked=None if supported and model.get('status') in ('E2E_VERIFIED','SMOKE_TESTED','RUNTIME_VERIFIED','ADAPTER_IMPLEMENTED') else ('QUARANTINED','Image compute path requires quarantined GPU') if family==42 else ('BLOCKED',model.get('reason','Asset/runtime/resource gate not satisfied'))
  if blocked is None:
   missing=[a.get('path','UNKNOWN') for a in model.get('assets',[]) if not Path(a.get('path','')).is_file()]
   runtime=Path(model.get('runtime_path',''))
   if runtime.is_absolute() and not runtime.is_file():missing.append(str(runtime))
   if missing:blocked=('BLOCKED','Asset/runtime no longer present: '+', '.join(missing))
  out[fid]=dict(id=fid,name=model['id'],description='Model-specific adapter; catalog remains the asset source of truth',category='H',module='serve/hydra_lab_native_tasks.py' if family in (41,42,43) or 'Bonsai' in model['id'] else 'serve/hydra_lab_audio_adapter.py' if family==40 else 'serve/hydra_lab_benchmarks.py',runner='Workspace.execute',provider=model.get('runtime_path','NOT_AVAILABLE'),entry_point='/lab/benchmarks/run',experimental=True,backend='GPU' if family==42 else 'CPU',control='switch' if blocked is None else 'request_only',dependencies=[ids[family]],incompatibilities=[],profiles=['cpu'] if blocked is None else [],parameters_schema={},default_desired=model['id']=='local/Qwen3-0.6B-Q8_0',build_status='EXISTING_RUNTIME' if model.get('runtime_path') else 'RUNTIME_NOT_ATTESTED',verification={'kind':'CATALOG_EVIDENCE','status':model.get('status')},prerequisites=['Catalog asset/runtime identity and per-task memory admission'],rollback='OFF blocks new adapter requests; in-flight request completes under its original snapshot',parameter_scope='Request parameters remain in the existing runner; no ignored extra fields',blocked=blocked,evidence_runs=model.get('benchmarks',[]))
 from serve.hydra_acceptance_v18 import verified_evidence
 campaign_proof=verified_evidence()
 from serve.hydra_acceptance_v19 import verified_evidence as evidence19
 campaign19_proof=evidence19()
 if campaign_proof['Vulkan']['request_count']:
  out['runtime.vulkan'].update(build_status='V18_GPU_E2E_VERIFIED',verification=dict(kind='REAL_GPU_GENERATION',v17_recovery=gpu_proof,v18=campaign_proof['Vulkan'],scope='Exact persisted runs; quality and performance are separate assessments'),evidence_runs=gpu_proof['run_ids']+campaign_proof['Vulkan']['run_ids'],profiles=['v8-v18-gpu-qwen; exact finite campaign only','v8-recovery-qwen; finite historical recovery only'])
 for number in (2,7):
  feature=out[ids[number]];feature.update(dependencies=['runtime.vulkan'],entry_point='v8-v18-gpu-qwen; frozen planned flags',parameter_scope='Finite v18 campaign only; OFF rejects the corresponding v18 configuration; historical profiles remain quarantined',verification=dict(kind='SCOPED_GPU_EXECUTION',v18=campaign_proof['Vulkan']))
  if number==7:feature['name']='Flash Attention Vulkan off/on/auto (campagna finita)'
  feature['entry_point']='v8-v18/v19-gpu-qwen; exact frozen planned flags'
  feature['parameter_scope']='Finite explicit v18/v19 grant; OFF rejects requested configuration; closed grant never rearms'
 if campaign19_proof['Vulkan']['request_count']:
  out['runtime.vulkan']['verification']['v19']=campaign19_proof['Vulkan']
  out['runtime.vulkan']['evidence_runs']+=campaign19_proof['Vulkan']['run_ids']
  out['runtime.vulkan']['profiles'].append('v8-v19-gpu-qwen; exact finite grant only')
 qwen=out.get(adapter_id('local/Qwen3-0.6B-Q8_0'))
 if qwen is not None and campaign_proof['CPU']['request_count']:
  qwen.update(build_status='REAL_QWEN_CPU_RUNTIME_VERIFIED',verification=dict(kind='REAL_GENERATION; no general quality claim',**campaign_proof),evidence_runs=campaign_proof['CPU']['run_ids']+campaign_proof['Vulkan']['run_ids'])
 from serve.hydra_capability_contracts import BLOCKERS
 for fid,feature in out.items():
  number=feature_number(fid)
  if number in (15,16,31,32,36,46):
   family={15:'moe',16:None,31:'weight_tiering',32:'speculative',36:'remote',46:'full35b'}[number]
   feature['implementation_v23']=dict(level='IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED',module='serve/hydra_capability_contracts.py',dependency=BLOCKERS.get(family),execution_enabled=number==16)
   if family:feature['blocked']=('BLOCKED',BLOCKERS[family]);feature['prerequisites'].append(BLOCKERS[family])
 for feature in out.values():
  if feature_number(feature['id'])==15:
   from serve.hydra_capability_contracts import native_moe_target
   try:
    target=native_moe_target(H.parent);feature['native_target_v24']=target
    feature['blocked']=('BLOCKED',target['dependency'])
    feature['prerequisites']=[p for p in feature['prerequisites'] if p!='COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED']+[target['dependency']]
    feature['implementation_v24']=dict(classification='BLOCCATO DA DIPENDENZE',consumer='native_moe_target + shared admission; native engine not promoted',dependency=target['dependency'])
    feature['description']='Existing Strata native MoE runtime, dense pack, native type42 expert layout and tokenizer found locally. Weight identity/execution admission is not attested by metadata presence; Bonsai dense is a different target. No new native model execution.'
   except (OSError,ValueError,KeyError,IndexError) as exc:feature['native_target_v24']=dict(execution_enabled=False,reason=str(exc))
 return out

class FeatureControl:
 def __init__(self,root,catalog=None,admission=None):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'benchmarks.sqlite';self.catalog=catalog or (lambda:[])
  if admission is None:
   from serve.hydra_execution_v10 import admission_status
   admission=admission_status
  self.admission=admission;self._snapshot=None
  with self.db() as c:
   c.execute('CREATE TABLE IF NOT EXISTS feature_revisions(version INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
   c.execute('CREATE TRIGGER IF NOT EXISTS feature_revisions_no_update BEFORE UPDATE ON feature_revisions BEGIN SELECT RAISE(ABORT,"immutable feature revision"); END')
   c.execute('CREATE TRIGGER IF NOT EXISTS feature_revisions_no_delete BEFORE DELETE ON feature_revisions BEGIN SELECT RAISE(ABORT,"immutable feature revision"); END')
   if not c.execute('SELECT 1 FROM feature_revisions LIMIT 1').fetchone():
    d=definitions(self.catalog());features={k:dict(desired=v['default_desired'],parameters={p:s['default'] for p,s in v['parameters_schema'].items()}) for k,v in d.items()}
    c.execute('INSERT OR IGNORE INTO feature_revisions VALUES(0,?)',(json.dumps(dict(schema_version=SCHEMA,version=0,features=features,timestamp=stamp(),source='initial safe lab defaults; no model started',previous_version=None,changes={},validation='VALID'),ensure_ascii=False),))
 @contextmanager
 def db(self):
  connection=sqlite3.connect(self.path,timeout=5)
  try:
   with connection:yield connection
  finally:connection.close()
 def export(self):
  with self.db() as c:return json.loads(c.execute('SELECT payload FROM feature_revisions ORDER BY version DESC LIMIT 1').fetchone()[0])
 def history(self):
  with self.db() as c:return [json.loads(v[0]) for v in c.execute('SELECT payload FROM feature_revisions ORDER BY version DESC')]
 def defs(self):return definitions(self.catalog())
 def _effective(self,definition,values,seen=None):
  fid=definition['id'];value=values[fid]
  if not value['desired']:return 'INACTIVE','OFF; no new request may use this feature'+('; '+definition['blocked'][1] if definition['blocked'] else '')
  if definition['blocked']:
   from serve.hydra_gpu_recovery_v16 import feature_available
   from serve.hydra_acceptance_campaign import available as campaign_available
   from serve.hydra_engine_v20 import available as v20_available
   exception=campaign_available() if feature_number(fid) in (2,7) else fid=='runtime.vulkan' and (feature_available() or campaign_available())
   if (fid=='runtime.vulkan' or feature_number(fid)==2) and v20_available():exception=True
   from serve.hydra_engine_v21 import available as v21_available
   if (fid=='runtime.vulkan' or feature_number(fid) in (2,16)) and v21_available():exception=True
   if not exception:return tuple(definition['blocked'])
  if fid.startswith('adapter.') or feature_number(fid) in (1,20,21,22,38,39,40,41,43):
   import psutil
   native=fid.startswith('adapter.') and any(k in fid for k in ('Bonsai','Huihui','cdiamond','mudler','YuE2'))
   minimum=32 if native else 12
   if psutil.virtual_memory().available<minimum*1024**3:return 'BLOCKED',str(minimum)+' GiB free RAM required by the admitted CPU path; monitored resources are not a hard cap'
  for dep in definition['dependencies']:
   if not values.get(dep,{}).get('desired'):return 'BLOCKED','DEPENDENCY: '+dep
  return 'ACTIVE','Applied policy for future requests; does not imply a loaded model or an executing operation'
 def list(self):
  config=self.export();d=self.defs();rows=[];admission=self.admission();pending=admission.get('state') not in ('IDLE','RELEASED') and admission.get('request',{}).get('feature_version',config['version'])!=config['version']
  evidence={}
  try:
   with self.db() as c:
    for key,a,b in c.execute("SELECT id,json_extract(payload,'$.feature_ids'),json_extract(payload,'$.feature_control.required') FROM runs WHERE json_type(payload,'$.feature_ids')='array' OR json_type(payload,'$.feature_control.required')='array'"):
     for fid in set(json.loads(a or '[]')+json.loads(b or '[]')):evidence.setdefault(fid,[]).append(key)
  except sqlite3.OperationalError:pass
  for fid,item in d.items():
   item=dict(item,evidence_runs=list(dict.fromkeys(item['evidence_runs']+evidence.get(fid,[]))))
   value=config['features'].get(fid,dict(desired=False,parameters={k:v['default'] for k,v in item['parameters_schema'].items()}));values=dict(config['features']);values[fid]=value;effective,reason=self._effective(item,values)
   if pending and item['control']=='switch':effective,reason='PENDING_RESTART','Current admitted run retains its immutable snapshot; change applies to the next session'
   if admission.get('state')=='CLEANUP_BLOCKED' and not value['desired']:effective,reason='FAILED_TO_DISABLE','Cleanup not verified; cannot confirm release. All new admissions are blocked.'
   rows.append(dict(item,desired=value['desired'],parameters=value['parameters'],effective=effective,reason=reason,configuration_version=config['version'],timestamp=config['timestamp'],change_reference='feature_revisions/'+str(config['version'])))
  counts={state:sum(r['effective']==state for r in rows) for state in ('ACTIVE','INACTIVE','BLOCKED','QUARANTINED','PENDING_RESTART','FAILED_TO_DISABLE','UNSUPPORTED','NOT_TESTED')}
  return dict(schema_version=SCHEMA,version=config['version'],features=rows,counts=dict(total=len(rows),experimental=sum(r['experimental'] for r in rows),unavailable=sum(bool(r['blocked']) for r in rows),**counts),admission=admission)
 def get(self,fid):
  try:return next(r for r in self.list()['features'] if r['id']==fid)
  except StopIteration:raise FeatureError('UNKNOWN_FEATURE: '+fid)
 def _candidate(self,config,changes,d=None):
  if not isinstance(changes,dict) or len(changes)>160:raise FeatureError('INVALID_CHANGES')
  d=d or self.defs();values=copy.deepcopy(config['features'])
  for fid,patch in changes.items():
   if fid not in d or not isinstance(patch,dict) or set(patch)-{'desired','parameters'}:raise FeatureError('UNKNOWN_FEATURE_OR_FIELD: '+fid)
   values.setdefault(fid,dict(desired=False,parameters={k:s['default'] for k,s in d[fid]['parameters_schema'].items()}))
   if 'desired' in patch:
    if type(patch['desired']) is not bool:raise FeatureError('INVALID_BOOLEAN')
    if d[fid]['control']=='mandatory' and not patch['desired']:raise FeatureError('MANDATORY: '+fid)
    values[fid]['desired']=patch['desired']
   if 'parameters' in patch:
    params=patch['parameters'];schema=d[fid]['parameters_schema']
    if not isinstance(params,dict) or set(params)-set(schema):raise FeatureError('UNSUPPORTED_PARAMETER: '+fid)
    for name,v in params.items():
     s=schema[name]
     if type(v) is not int or not s['min']<=v<=s['max']:raise FeatureError('PARAMETER_OUT_OF_RANGE: '+fid+'/'+name)
    values[fid]['parameters'].update(params)
   for name,schema in d[fid]['parameters_schema'].items():values[fid]['parameters'].setdefault(name,schema['default'])
  for fid,v in values.items():
   if v['desired'] and fid in d:
    for dep in d[fid]['dependencies']:
     if not values.get(dep,{}).get('desired'):raise FeatureError('DEPENDENCY: '+fid+' requires '+dep)
  nums={feature_number(k):v for k,v in values.items() if feature_number(k)}
  if nums[29]['desired'] and nums[28]['desired']:raise FeatureError('IOCP_REQUIRES_MMAP_OFF; disable V7-E-028 explicitly')
  return values
 def preview(self,changes,include_dependencies=False,include_dependents=False):
  config=self.export();d=self.defs();changes=copy.deepcopy(changes)
  # Dependency expansion is explicit and returned for review before saving.
  for _ in range(len(d)):
   previous=json.dumps(changes,sort_keys=True)
   for fid,p in list(changes.items()):
    if fid not in d:raise FeatureError('UNKNOWN_FEATURE: '+fid)
    if p.get('desired') is True and include_dependencies:
     for dep in d[fid]['dependencies']:
      if not config['features'].get(dep,{}).get('desired') and not changes.get(dep,{}).get('desired'):changes[dep]={'desired':True}
    if p.get('desired') is False and include_dependents:
     for other,item in d.items():
      if fid in item['dependencies'] and (changes.get(other,{}).get('desired',config['features'].get(other,{}).get('desired'))):changes[other]={'desired':False}
   if previous==json.dumps(changes,sort_keys=True):break
  values=self._candidate(config,changes);blocked=[]
  for fid,p in changes.items():
   state,reason=self._effective(d[fid],values)
   if values[fid]['desired'] and state!='ACTIVE':blocked.append(dict(id=fid,effective=state,reason=reason))
  return dict(expected_version=config['version'],changes=changes,blocked=blocked,starts_inference=False)
 def apply(self,request):
  if not isinstance(request,dict) or set(request)-{'expected_version','changes','allow_blocked','source'}:raise FeatureError('INVALID_CONFIG_REQUEST')
  if type(request.get('expected_version')) is not int or type(request.get('allow_blocked',False)) is not bool:raise FeatureError('INVALID_VERSION_OR_POLICY')
  source=request.get('source','user');
  if not isinstance(source,str) or len(source)>120:raise FeatureError('INVALID_SOURCE')
  d=self.defs() # Catalog may update its own metadata; never refresh it inside our write transaction.
  with self.db() as c:
   c.execute('BEGIN IMMEDIATE');old=json.loads(c.execute('SELECT payload FROM feature_revisions ORDER BY version DESC LIMIT 1').fetchone()[0])
   if old['version']!=request['expected_version']:raise FeatureError('VERSION_CONFLICT')
   values=self._candidate(old,request.get('changes',{}),d)
   for fid in request.get('changes',{}):
    state,reason=self._effective(d[fid],values)
    if values[fid]['desired'] and state!='ACTIVE' and not request.get('allow_blocked'):raise FeatureError('BLOCKED_TRANSACTION: '+fid+' '+reason)
   row=dict(schema_version=SCHEMA,version=old['version']+1,features=values,timestamp=stamp(),source=source,previous_version=old['version'],changes={fid:dict(previous=old['features'].get(fid),current=values[fid]) for fid in request.get('changes',{})},validation='VALID; blocked desires never execute',application='PENDING_RESTART' if self.admission().get('state') not in ('IDLE','RELEASED') else 'APPLIED_POLICY')
   c.execute('INSERT INTO feature_revisions VALUES(?,?)',(row['version'],json.dumps(row,ensure_ascii=False,allow_nan=False)))
  return self.list()
 def import_config(self,value,expected_version):
  if not isinstance(value,dict) or type(value.get('schema_version')) is not int or value.get('schema_version')!=SCHEMA or set(value)-{'schema_version','version','features','timestamp','source','previous_version','changes','validation','application'}:raise FeatureError('INVALID_SCHEMA')
  return self.apply(dict(expected_version=expected_version,changes=value.get('features'),allow_blocked=True,source='explicit configuration import'))
 def rollback(self,version,expected_version):
  if type(version) is not int:raise FeatureError('INVALID_VERSION')
  with self.db() as c:row=c.execute('SELECT payload FROM feature_revisions WHERE version=?',(version,)).fetchone()
  if not row:raise FeatureError('UNKNOWN_VERSION')
  return self.apply(dict(expected_version=expected_version,changes=json.loads(row[0])['features'],allow_blocked=True,source='rollback to revision '+str(version)))
 def preset(self,name):
  if name=='hydra-gpu-throughput-v19':
   from serve.hydra_performance_v19 import promoted_preset
   return promoted_preset(self)
  if name=='hydra-cpu-fastpath-v2':
   from serve.hydra_performance_v15 import promoted_preset
   return promoted_preset(self)
  d=self.defs();by_n={feature_number(k):k for k in d if feature_number(k)}
  if name not in ('cpu-stable','graph-cpu','multimodal-cpu','diagnostic','gpu-quarantined','hydra-local-complete-v1','hydra-gpu-prepared-v1'):raise FeatureError('UNKNOWN_PRESET')
  enabled={1,24,28,38,53,54}|MANDATORY
  if name=='graph-cpu':enabled|={20,21,22,23}
  if name=='hydra-local-complete-v1':enabled|={3,20,21,22,23,39}
  if name=='multimodal-cpu':enabled|={39,40,41,43}
  changes={fid:{'desired':n in enabled} for n,fid in by_n.items() if d[fid]['control']!='mandatory'}
  for fid,item in d.items():
   if fid.startswith('adapter.'):changes[fid]={'desired':item['default_desired'] or name in ('multimodal-cpu','hydra-local-complete-v1') and not item['blocked']}
  for fid in d:
   if fid.startswith('runtime.'):changes[fid]={'desired':False}
  if name in ('gpu-quarantined','hydra-gpu-prepared-v1'):changes['runtime.vulkan']={'desired':True}
  plan=self.preview(changes,include_dependencies=True,include_dependents=True);plan['preset_id']=name if name in ('hydra-local-complete-v1','hydra-gpu-prepared-v1') else name+'-schema1';return plan
 def resolve(self,body):
  from serve.hydra_capability_contracts import guard_request
  guard_request(body)
  config=self._snapshot or self.export();d=self.defs();ids={feature_number(k):k for k in d if feature_number(k)};required=[];path=body.get('path');r=body.get('request',{})
  if config['features'][ids[29]]['desired'] and 'feature_probe' not in body:
   if path in ('/lab/chat','/lab/performance') or not path and body.get('model_id','local/Qwen3-0.6B-Q8_0')=='local/Qwen3-0.6B-Q8_0' and body.get('profile','cpu')=='cpu':required.append(ids[29])
   elif not path and body.get('model_id')=='prism-ml/Ternary-Bonsai-2-27B-gguf' and body.get('profile')=='cpu':
    if body.get('thinking') not in ('on','off'):raise FeatureError('NATIVE_TEMPLATE_SERVER_REQUIRED: Prism IOCP uses its admitted template-aware CPU server')
    required.append(ids[29])
   elif path not in ('/lab/ingest','/lab/retrieve','/lab/provider-off'):raise FeatureError('IOCP_SCOPE: only Qwen CPU or Bonsai template CPU supported; disable loader for other adapters')
  if 'feature_probe' in body:
   if not isinstance(body['feature_probe'],str):raise FeatureError('INVALID_FEATURE_ID')
   required=[body['feature_probe']]
  elif path:
   nums={'/lab/ingest':[20],'/lab/retrieve':[20]+([21] if r.get('variant')=='H1' else [21,22] if r.get('variant')=='H1v2' else []),'/lab/chat':[1,38]+([20,23] if r.get('graph') else []),'/lab/score':[1,39],'/lab/score-prefix':[45],'/lab/system-one-bridge':[44],'/lab/provider-off':[]}.get(path)
   if path=='/lab/performance':nums=[1,38]
   if nums is None:raise FeatureError('UNSUPPORTED_ENTRY_POINT')
   if path=='/lab/chat' and r.get('graph') and r.get('variant') in ('H1','H1v2'):
    nums=nums+([21,22] if r['variant']=='H1v2' else [21])
   required.extend(ids[n] for n in nums)
   if path in ('/lab/chat','/lab/performance'):required.append(adapter_id('local/Qwen3-0.6B-Q8_0'))
   if (path=='/lab/retrieve' or path=='/lab/chat' and r.get('graph')) and config['features'][ids[26]]['desired']:required.append(ids[26])
   if (path=='/lab/retrieve' or path=='/lab/chat' and r.get('graph')) and config['features'][ids[17]]['desired']:required.append(ids[17])
  else:
   model=body.get('model_id','local/Qwen3-0.6B-Q8_0');required.append(adapter_id(model))
   if body.get('graph'):
    if config['features'][ids[26]]['desired']:
     required.append(ids[26])
     if config['features'][ids[17]]['desired']:required.append(ids[17])
    if config['features'][ids[24]]['desired']:required.append(ids[24])
    required.extend(ids[n] for n in ([20,23]+([21,22] if body.get('variant')=='H1v2' else [21] if body.get('variant')=='H1' else [])))
   if str(body.get('profile','')).startswith('v20-bonsai-') or body.get('profile')=='v21-bonsai-hybrid':required.append(ids[2])
   if body.get('checkpoint'):
    if body.get('profile') not in ('cpu','v21-bonsai-hybrid') or body.get('samples')!=2:raise FeatureError('NATIVE_STATE_PROFILE_AND_REUSE_REQUIRED')
    required.extend(ids[n] for n in (3,6,16))
   if body.get('profile') in ('v8-v18-cpu-qwen','v8-v18-gpu-qwen','v8-v19-cpu-qwen','v8-v19-gpu-qwen'):
    from serve.hydra_acceptance_campaign import required_controls
    required.extend(ids[n] for n in required_controls(body))
   if body.get('profile','cpu') not in ('cpu','v8-v18-cpu-qwen','v8-v19-cpu-qwen') and not str(body.get('profile')).startswith('prism-v5-cpu-'):required.insert(0,'runtime.vulkan')
  def check(fid,seen):
   if fid in seen:return
   seen.add(fid)
   if fid not in d or fid not in config['features']:raise FeatureError('FEATURE_BLOCKED: UNKNOWN '+fid)
   state,reason=self._effective(d[fid],config['features'])
   if state!='ACTIVE':raise FeatureError('FEATURE_BLOCKED: '+fid+' '+state+' '+reason)
   for dep in d[fid]['dependencies']:check(dep,seen)
  used=set()
  if path=='/lab/performance':
   for number in (3,6,29):
    if config['features'][ids[number]]['desired']:required.append(ids[number])
   if r.get('workload')=='scoring':
    required.append(ids[39])
    for number in (13,14):
     if config['features'][ids[number]]['desired']:required.append(ids[number])
  if not path and body.get('profile')=='cpu' and body.get('model_id','local/Qwen3-0.6B-Q8_0')=='local/Qwen3-0.6B-Q8_0' and config['features'][ids[3]]['desired']:required.append(ids[3])
  if config['features'][ids[34]]['desired']:required.append(ids[34])
  if path=='/lab/chat' or not path and body.get('profile','cpu')=='cpu' and body.get('model_id','local/Qwen3-0.6B-Q8_0')=='local/Qwen3-0.6B-Q8_0':
   for number in (6,9,11,28,29):
    if config['features'][ids[number]]['desired']:required.append(ids[number])
  if not path and body.get('thinking') in ('on','off'):
   for number in (6,9,11,28,29):
    if config['features'][ids[number]]['desired']:required.append(ids[number])
   if body.get('samples',1)>1:required.append(ids[3])
  if path in ('/lab/chat','/lab/performance') and config['features'][ids[35]]['desired']:required.append(ids[35])
  if config['features'][ids[35]]['desired'] and not path and body.get('thinking') in ('on','off'):required.append(ids[35])
  if path in ('/lab/score','/lab/score-prefix','/lab/system-one-bridge'):
   for number in (13,14):
    if config['features'][ids[number]]['desired']:required.append(ids[number])
  for fid in required:check(fid,used)
  return dict(version=config['version'],required=sorted(used),settings=copy.deepcopy(config['features']))
 def begin(self,body):
  resolved=self.resolve(body);self._snapshot=self.export()
  if self._snapshot['version']!=resolved['version']:self._snapshot=None;raise FeatureError('VERSION_CONFLICT; retry only explicitly')
  return resolved
 def end(self):self._snapshot=None
 def setting(self,number):
  config=self._snapshot or self.export()
  return next(v for k,v in config['features'].items() if feature_number(k)==number)

def features_api(control,operation,body=None):
 if operation=='list':return control.list()
 if operation=='history':return control.history()
 if operation=='export':return control.export()
 if not isinstance(body,dict):raise FeatureError('OBJECT_REQUIRED')
 if operation=='preview':return control.preview(**body)
 if operation=='apply':return control.apply(body)
 if operation=='rollback':return control.rollback(**body)
 if operation=='import':return control.import_config(**body)
 if operation=='preset':return control.preset(**body)
 if operation=='check':return control.get(body['feature_id'])
 raise FeatureError('UNKNOWN_FEATURE_OPERATION')

def runtime_options(control):
 """CPU Qwen and template-aware native settings; model-specific defaults stay in each adapter."""
 options=dict(threads=2,affinity_cpus=2,context=2048,max_tokens=128,seed=42,cache_prompt=False,mmap=True,model_io='standard')
 if control is None:return options
 for number,names in ((9,('threads','affinity_cpus')),(11,('context','max_tokens','seed'))):
  value=control.setting(number)
  if value['desired']:options.update({name:value['parameters'][name] for name in names})
 options.update(cache_prompt=control.setting(6)['desired'],mmap=control.setting(28)['desired'])
 loader=control.setting(29)
 options['model_io']=('candidate-standard' if loader['parameters'].get('loader_mode',0)==1 else 'iocp') if loader['desired'] else 'standard'
 return options

def check_native_policy(argv,request):
 """Fail closed for known model launchers bypassing the common resolver."""
 argv=list(map(str,argv));name=Path(argv[0]).name.lower()
 native=name in ('llama-server.exe','llama-cli.exe','llama-completion.exe','native_score.exe','native-score-v11.exe','native-score-v13.exe','native-score-v14.exe','native-score-recovery.exe','qwen36.exe','audiocpp_server.exe','locate-anything-cli.exe','yue-synth.exe','sd-cli.exe') or '--dense-worker' in argv
 metadata=len(argv)==2 and argv[1] in ('--help','--version','--list-devices')
 if native and not metadata and (type(request.get('feature_version')) is not int or not request.get('feature_required')):raise FeatureError('FEATURE_CONTROL_REQUIRED; legacy native launcher must enter the common resolver')

def policy_exists():
 path=Path(__file__).resolve().parents[1]/'data/hydra-benchmark-registry/benchmarks.sqlite'
 if not path.is_file():return False
 connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
 try:return bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_revisions'").fetchone())
 finally:connection.close()

def probe(workspace,body):
 """Admitted, non-generative refusal proof. Never a hardware capability test."""
 from serve.hydra_execution_v10 import exclusive_execute
 @exclusive_execute
 def admitted(ws,request,_key=None):
  from serve.hydra_lab_benchmarks import comparison_key
  timestamp=stamp();folder=ws.store.root/'runs'/_key;folder.mkdir(exist_ok=False)
  row=dict(run_id=_key,origin='SOFTWARE_VALIDATION',test_type='ADMISSION_TEST',status='PASS',timestamp=timestamp,finished_at=timestamp,model='HYDRA feature admission',model_hash=None,runtime='shared feature resolver; no provider started',runtime_hash=None,backend='SOFTWARE_ONLY',quantization='NOT_APPLICABLE',profile='feature-control-v12',parameters={},configuration={},prompt_id=request['feature_probe'],prompt_hash=None,template_hash=None,samples=[],warmup=[],summary={},quality_gate='NOT_APPLICABLE',cleanup=True,exit_code=0,error=None,artifacts=str(folder),log_path=str(folder/'feature-admission.json'),feature_ids=[request['feature_probe']],events=[{'at':timestamp,'kind':'feature_admission_only','detail':'No model, tokenizer or native provider executed'}],real_execution_kind='software admission only; not inference')
  row['comparison_key']=comparison_key(row);(folder/'feature-admission.json').write_text(json.dumps(row),encoding='utf8');return row
 return admitted(workspace,dict(feature_probe=body['feature_id'],model_id='feature-control/'+body['feature_id'],profile='feature-control-v12'))
