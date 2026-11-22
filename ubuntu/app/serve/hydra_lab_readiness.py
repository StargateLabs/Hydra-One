"""Readiness is separate from historical compatibility and hardware evidence."""
from pathlib import Path

def catalog_readiness(row):
 status=row.get('status','CATALOGED')
 if status in ('ASSET_MISSING','RUNTIME_MISSING','RESOURCE_BLOCKED','LICENSE_REVIEW_REQUIRED'):return dict(state='BLOCKED',reason=row.get('reason',status))
 if status in ('ARCHITECTURE_UNSUPPORTED','QUANTIZATION_UNSUPPORTED'):return dict(state='UNSUPPORTED',reason=row.get('reason',status))
 if status=='E2E_VERIFIED':return dict(state='VERIFIED',reason='Evidence applies only to the recorded variant/backend; GPU quarantine still applies')
 if status in ('ADAPTER_IMPLEMENTED','RUNTIME_VERIFIED','SMOKE_TESTED'):return dict(state='EXPERIMENTAL',reason='Use only the admitted laboratory adapter; this is not new E2E evidence')
 return dict(state='NOT_TESTED',reason=row.get('reason','No completed functional evidence'))

def readiness(lab):
 from serve.hydra_one import runtime
 engine=runtime() # validates the preserved bundle and imports metadata; no model/worker
 marker=Path(__file__).resolve().parents[1]/'data/hydra-v8-safety-stop.json'
 return dict(bundle_metadata_loaded_without_model=True,gpu={'state':'BLOCKED','reason':'BLOCKED_GPU_QUARANTINE; ErrorDeviceLost cause UNKNOWN'} if marker.exists() else {'state':'NOT_TESTED','reason':'GPU recovery not attested'},functional_paths=['/lab/chat','/lab/score','/lab/ingest','/lab/retrieve'],CPU={'state':'READY_FOR_TEST' if Path(lab.profile['runtime']).is_dir() and Path(lab.profile['model']).is_file() else 'BLOCKED','reason':'Explicit CPU admission, asset hashes and resources are checked before each execution'},operational_defaults_changed=False)
