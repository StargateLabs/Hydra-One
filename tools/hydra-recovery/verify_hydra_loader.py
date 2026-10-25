import hashlib,json,os,re,socket,sys,time,urllib.error,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from serve.hydra_execution_v10 import Reservation,guarded_popen
from serve.hydra_feature_control import FeatureControl
native=ROOT.parent/'HYDRA/engine_completion_v22/prism-cpu-build/bin'
model=ROOT/'output/verification/smollm2-export-f16.gguf'
out=ROOT/'output/verification/hydra-loader-recovery'
out.mkdir(parents=True,exist_ok=True)
control=FeatureControl(ROOT/'data/hydra-benchmark-registry')
resolution=control.resolve({'feature_probe':'V7-A-001'})
lease=Reservation(dict(run_id='recovery-loader-'+uuid.uuid4().hex,backend='CPU',memory_limit_bytes=8*1024**3,
    feature_version=resolution['version'],feature_required=resolution['required']))
lease.acquire()
results=[]
try:
 for mode in ('standard','iocp'):
  with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
  log=out/(mode+'.log')
  env=dict(os.environ,HYDRA_MODEL_IO=mode,CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',ROCR_VISIBLE_DEVICES='',OMP_NUM_THREADS='2')
  env.pop('GGML_BACKEND_PATH',None)
  args=[str(native/'llama-server.exe'),'-m',str(model),'--host','127.0.0.1','--port',str(port),'-ngl','0','--device','none','--no-mmap','-c','512','-t','2','-tb','2','--parallel','1','--jinja']
  with log.open('wb') as stream:
   child=guarded_popen(args,cwd=native,env=env,stdout=stream,stderr=stream,creationflags=0x08000000)
   try:
    deadline=time.monotonic()+60
    while True:
     if child.poll() is not None:raise RuntimeError('Loader exited: '+log.read_text(errors='replace')[-2000:])
     try:
      with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:
       if response.status==200:break
     except (OSError,urllib.error.URLError):pass
     if time.monotonic()>deadline:raise TimeoutError('Native loader startup')
     time.sleep(.15)
    request=dict(messages=[dict(role='user',content='Say hello in one short sentence.')],max_tokens=32,temperature=0,seed=42,cache_prompt=False,stream=False)
    raw=json.dumps(request).encode()
    req=urllib.request.Request(f'http://127.0.0.1:{port}/v1/chat/completions',raw,{'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=40) as response:reply=json.load(response)
    text=reply['choices'][0]['message']['content']
    assert text.strip() and reply['usage']['completion_tokens']>0
   finally:
    if child.poll() is None:child.terminate()
    child.wait(timeout=10)
  content=log.read_text(errors='replace')
  counters=re.findall(r'HYDRA_READER mode='+mode+r' consumer_bytes=(\d+) cleanup=closed',content)
  assert counters and sum(map(int,counters))>0,'Missing tensor consumer telemetry'
  item=dict(mode=mode,response=reply,tensor_consumer_bytes=sum(map(int,counters)),log=str(log))
  if mode=='iocp':
   rows=re.findall(r'HYDRA_IOCP consumer_bytes=(\d+) physical_bytes=(\d+) completions=(\d+) cleanup=closed',content)
   assert rows and sum(int(row[0]) for row in rows)==item['tensor_consumer_bytes']
   item['iocp']=dict(consumer_bytes=sum(int(r[0]) for r in rows),physical_bytes=sum(int(r[1]) for r in rows),completions=sum(int(r[2]) for r in rows))
  results.append(item)
 assert results[0]['response']['choices'][0]['message']['content']==results[1]['response']['choices'][0]['message']['content'],'Standard/IOCP text parity failed'
 assert results[0]['tensor_consumer_bytes']==results[1]['tensor_consumer_bytes']
 lease.verify_cleanup()
 report=dict(status='PASS',model=str(model),model_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),results=results,
    text_parity=True,cleanup=True,scope='Real recovered SmolLM2 CPU generation and tensor reads. No Qwen/Bonsai model parity, GPU or performance promotion claimed.')
 (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf8')
 lease.release(persisted=True)
 print(json.dumps(dict(status='PASS',tensor_bytes=results[0]['tensor_consumer_bytes'],iocp=results[1]['iocp'],output=results[0]['response']['choices'][0]['message']['content'])))
except BaseException:
 lease.verify_cleanup();lease.release(persisted=True)
 raise
