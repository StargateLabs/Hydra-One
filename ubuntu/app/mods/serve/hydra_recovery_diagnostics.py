"""Read-only interpretation of recorded native evidence; never launches a model."""
import hashlib,collections

def classify_native_error(log):
 lost=any(x in log for x in ('ErrorDeviceLost','device lost on Vulkan','VK_ERROR_DEVICE_LOST'))
 return dict(error_code='GPU_DEVICE_LOST' if lost else 'UNCLASSIFIED',stop_gpu_sequence=lost,physical_gpu_failure='NOT_ESTABLISHED',cause='UNKNOWN',coordination_fault='must be assessed independently from process/lease evidence')

def analyze_samples(samples):
 hashes=[hashlib.sha256(s['output'].encode('utf8')).hexdigest() for s in samples]
 responses=[s.get('response',{}) for s in samples];settings=[r.get('generation_settings',{}) for r in responses];reused=[r.get('timings',{}).get('cache_n') for r in responses];tokens=[r.get('tokens') for r in responses]
 return dict(samples=len(samples),text_repeatable=bool(samples) and len(set(hashes))==1,output_hash_counts=dict(collections.Counter(hashes)),seeds=[s.get('seed') for s in settings],temperatures=[s.get('temperature') for s in settings],sampler_settings_identical=bool(settings) and all(s==settings[0] for s in settings),rng_cause='NOT_ESTABLISHED',output_token_ids_verified=bool(samples) and all(isinstance(t,list) and len(t)>0 and all(type(x) is int for x in t) for t in tokens),native_reused_tokens=reused,cache_hit_samples=sum(type(n) is int and n>0 for n in reused),semantic_correctness='NOT_VERIFIED',cache_final_size_is_not_hit=True)


def safe_environment(environment):
 names=('GGML_BACKEND_PATH','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','HIP_VISIBLE_DEVICES','ROCR_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES','LLAMA_ARG_DEVICE','LLAMA_ARG_N_GPU_LAYERS','LLAMA_ARG_FLASH_ATTN','LLAMA_ARG_BATCH','LLAMA_ARG_UBATCH')
 return {k:environment[k] for k in names if k in environment}

def persist_fault(log,marker,evidence,identity):
 import json,os,uuid
 from pathlib import Path
 result=classify_native_error(log)
 if not result['stop_gpu_sequence']:return result
 data=dict(result,identity=identity)
 destination=Path(evidence)/('native-device-loss-'+uuid.uuid4().hex+'.json');destination.write_text(json.dumps(data,indent=2),encoding='utf8')
 marker=Path(marker);marker.parent.mkdir(parents=True,exist_ok=True)
 try:
  with marker.open('x',encoding='utf8') as f:json.dump(data,f,indent=2)
 except FileExistsError:pass
 return result
