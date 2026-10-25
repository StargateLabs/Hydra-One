"""One-way, idempotent import of native historical reports into the shared registry."""
import hashlib,json
from pathlib import Path

def import_native_reports(store,root):
 from serve.hydra_lab_benchmarks import now,summary,comparison_key
 audit=[]
 for file in sorted((Path(root)/'data/benchmarks').glob('*.json')):
  try:source=json.loads(file.read_text(encoding='utf-8'))
  except (ValueError,OSError):continue
  if source.get('publisher')=='hydra-benchmark-registry-v2':continue
  if source.get('schema_version')!=1:continue
  checksum=hashlib.sha256(file.read_bytes()).hexdigest();key='legacy-native-'+hashlib.sha256((file.name+checksum).encode()).hexdigest()[:24];engine=source.get('engine',{});samples=[];warmup=[]
  for v in source.get('rows',[]):
   if not isinstance(v,dict):continue
   sample={'e2e_ms':v.get('wall_s')*1000 if isinstance(v.get('wall_s'),(int,float)) else None,'decode_ms':v.get('decode_ms'),'decode_tps':v.get('decode_tok_s'),'prefill_ms':v.get('prefill_ms'),'prefill_tps':v.get('prefill_tok_s'),'tokens':v.get('generated',v.get('output_tokens')),'prompt_tokens':v.get('prompt_tokens'),'ttft_ms':v.get('ttft_ms'),'output':v.get('output'),'original_row':v}
   (warmup if v.get('warmup') else samples).append(sample)
  status=source.get('status');row={'run_id':key,'origin':'IMPORTED_HISTORICAL','status':'FAIL' if status in ('failed','error','FAIL') else 'IMPORTED_HISTORICAL','timestamp':source.get('started_at') or __import__('datetime').datetime.fromtimestamp(file.stat().st_mtime,__import__('datetime').timezone.utc).isoformat(),'timestamp_basis':'original report timestamp or file mtime','model':engine.get('model',source.get('model','UNKNOWN')),'model_hash':source.get('model_sha256'),'runtime':engine.get('version','UNKNOWN'),'runtime_hash':source.get('binary_sha256'),'backend':engine.get('backend','NOT_AVAILABLE'),'quantization':engine.get('quantization','NOT_AVAILABLE'),'profile':source.get('label',file.stem),'configuration':{'engine':engine,'config_fingerprint':source.get('config_fingerprint')},'parameters':source.get('protocol',{}),'prompt_id':source.get('protocol',{}).get('prompt_set','historical-native'),'prompt_hash':source.get('protocol',{}).get('prompt_sha256'),'template_hash':None,'warmup':warmup,'samples':samples,'summary':summary(samples),'quality_gate':source.get('quality_gate','NOT_AVAILABLE'),'error':source.get('error'),'exit_code':source.get('exit_code'),'cleanup':'NOT_AVAILABLE: historical report','log_path':str(file),'log_kind':'historical source report, not a newly captured runtime log','artifacts':str(file.parent),'legacy_native_path':str(file),'original_status':status,'original_report_sha256':checksum,'original_result':source,'measurement_scope':'historical-native-report; original methodology retained','real_execution_kind':'historical report; no new execution','events':[{'at':now(),'kind':'historical_native_import','detail':{'source':str(file),'sha256':checksum,'new_inference':False}}]}
  row['comparison_key']=comparison_key(row);store.put(row,insert_only=True);audit.append({'source':str(file),'sha256':checksum,'run_id':key,'present':True})
 return audit
