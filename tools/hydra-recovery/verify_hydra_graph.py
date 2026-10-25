import hashlib,json,os,sys,tempfile,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
os.environ['HYDRA_LAB_MODE']='1'
from serve.hydra_one import runtime
runtime()
from serve.hydra_lab_modules import load
from serve.hydra_graph_memory import GraphMemory
from serve.hydra_execution_v10 import Reservation
from serve.hydra_feature_control import FeatureControl
module=load('graph_hybrid');second=load('graph_hybrid_v2')
model=ROOT/'models/embeddings/paraphrase-multilingual-MiniLM-L12-v2-56338cbb'
hashes={p.relative_to(model).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in model.rglob('*') if p.is_file()}
fp=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
resolution=FeatureControl(ROOT/'data/hydra-benchmark-registry').resolve({'feature_probe':'V7-A-001'})
lease=Reservation(dict(run_id='recovery-graph-'+uuid.uuid4().hex,backend='CPU',memory_limit_bytes=8*1024**3,
 feature_version=resolution['version'],feature_required=resolution['required']))
lease.acquire()
out=ROOT/'output/verification/hydra-graph-recovery';out.mkdir(parents=True,exist_ok=True)
try:
 with tempfile.TemporaryDirectory(prefix='hydra-recovery-') as tmp:
  folder=Path(tmp);corpus=folder/'corpus';corpus.mkdir()
  source=corpus/'aurora.txt';source.write_text('Il laboratorio Aurora ha pressione 3 bar e temperatura 18 gradi.',encoding='utf8')
  graph=GraphMemory.create(folder/'graph.sqlite',roots=[corpus]);identity=graph.ingest('lab',source)
  with module.LocalDenseProvider(ROOT/'.venv-ml/Scripts/python.exe',model,fp,stderr_path=out/('provider-'+uuid.uuid4().hex+'.log'),asset_hashes=hashes,startup_s=45) as provider:
   vectors=provider.encode(['pressione Aurora','pressione Aurora'],deadline=time.monotonic()+10)
   assert len(vectors)==2 and len(vectors[0])==384 and vectors[0]==vectors[1]
   results=[]
   for cls in (module.HybridLab,second.HybridLabV2):
    row=cls(graph,provider).retrieve('lab','Quale pressione registra Aurora?',[str(source)],deadline=time.monotonic()+10,enabled=True)
    assert row.nodes and row.nodes[0]['id']==identity
    results.append(dict(strategy=row.strategy,nodes=len(row.nodes),metrics=row.metrics))
   source.write_text('Modified source must not be reused',encoding='utf8')
   row=module.HybridLab(graph,provider).retrieve('lab','Quale pressione registra Aurora?',[str(source)],deadline=time.monotonic()+10,enabled=True)
   assert not row.nodes,'Stale source was forwarded'
  assert provider.proc.poll() is not None
 lease.verify_cleanup()
 report=dict(status='PASS',dimensions=384,repeat_vectors_identical=True,stale_source_rejected=True,owned_provider_stopped=True,results=results,model_fingerprint=fp)
 (out/'result.json').write_text(json.dumps(report,indent=2))
 lease.release(persisted=True)
 print(json.dumps(report))
except BaseException:
 lease.verify_cleanup();lease.release(persisted=True)
 raise
