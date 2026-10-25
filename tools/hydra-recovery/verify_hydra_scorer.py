import json,sys,time,uuid,os,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root));os.environ['HYDRA_LAB_MODE']='1'
from serve.hydra_one import runtime
runtime()
from serve.hydra_lab_modules import load
from serve.hydra_execution_v10 import Reservation
from serve.hydra_feature_control import FeatureControl
module=load('decision_scoring');folder=root.parent/'HYDRA/engine_completion_v22'
manifest=json.loads((folder/'qwen-loader-manifest.json').read_text());model=root/'output/verification/smollm2-export-f16.gguf'
data=root/'output/verification/hydra-scorer-recovery';data.mkdir(parents=True,exist_ok=True)
backend=module.NativeCPUBackend(folder/'native-score-recovery.exe',folder/manifest['runtime_relative'],model,{'files':manifest['files']},data,model_sha256=hashlib.sha256(model.read_bytes()).hexdigest())
resolution=FeatureControl(root/'data/hydra-benchmark-registry').resolve({'feature_probe':'V7-A-001'})
lease=Reservation(dict(run_id='recovery-scorer-'+uuid.uuid4().hex,backend='CPU',memory_limit_bytes=8*1024**3,feature_version=resolution['version'],feature_required=resolution['required']))
lease.acquire()
try:
 request=dict(backend='llama.cpp-cpu-capi',mode='continuation_logprobs',repeat=1,normalize='sum',prefix_text='The capital of France is',alternatives=[dict(id='paris',text=' Paris'),dict(id='london',text=' London')],deadline=time.monotonic()+40)
 first=module.score_alternatives(request,backend);assert first['status']=='complete',first
 request['deadline']=time.monotonic()+40;second=module.score_alternatives(request,backend)
 assert first['alternatives']==second['alternatives'],'Nondeterministic native scores'
 for row in first['alternatives']:assert row['tokens'] and abs(row['score']-sum(t['logprob'] for t in row['tokens']))<1e-8
 request.update(prefix_text='hel',alternatives=[dict(id='boundary',text='lo')],deadline=time.monotonic()+40)
 boundary=module.score_alternatives(request,backend)
 assert boundary['status']=='incomplete' and boundary['alternatives'][0]['status']=='unscorable_boundary'
 lease.verify_cleanup()
 report=dict(status='PASS',repeat_scores_identical=True,changed_token_boundary_rejected=True,cleanup=True,result=first,boundary=boundary)
 (data/'result.json').write_text(json.dumps(report,indent=2))
 lease.release(persisted=True)
 print(json.dumps(dict(status='PASS',scores=[dict(id=r['id'],score=r['score']) for r in first['alternatives']],boundary='rejected',cleanup=True)))
except BaseException:
 lease.verify_cleanup();lease.release(persisted=True);raise
