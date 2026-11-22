from serve.hydra_execution_v10 import guarded_popen
"""Explicit CPU family adapters for isolated, user-selected native tasks."""
import hashlib,json,os,subprocess,threading,time,uuid,math
from pathlib import Path

def text_arguments(model,body,capabilities=()):
 """Preserve legacy raw prompting unless an explicit supported thinking mode is requested."""
 budget=body['max_tokens'];thinking=body.get('thinking','auto')
 if type(budget) is not int or not 1<=budget<=128:raise ValueError('invalid native max_tokens')
 if thinking not in ('auto','on','off'):raise ValueError('invalid thinking mode')
 args=['-m',str(model),'-ngl','0','-c','512','-n',str(budget),'-t','2','-tb','2','--temp','0','--seed','42','--no-display-prompt','--no-warmup','-p',body['prompt']]
 if thinking=='auto':args+=['--no-conversation']
 else:
  if not {'reasoning','thinking_template'}<=set(capabilities):raise ValueError('THINKING_CAPABILITY: explicit template control is not attested by this CLI')
  args+=['--conversation','--single-turn','--reasoning',thinking]
  args+=['--chat-template-kwargs',json.dumps({'enable_thinking':thinking=='on'},separators=(',',':'))]
  if thinking=='off':args+=['--reasoning-budget','0']
 return args

def music_request(prompt):
 if not isinstance(prompt,str) or not prompt or len(prompt)>800:raise ValueError('bounded music style required')
 return {'style':prompt,'lyrics':'[Instrumental]','cot':'melody','duration':2.0,'steps':2,'lm_seed':42,'seed':42,'cfg_scale':1.0,'lm_batch_size':1,'synth_batch_size':1,'output_format':'wav16','abc_sampling':{'min_tokens':0,'max_tokens':256},'semantic_sampling':{'min_tokens':0,'max_tokens':64}}

def execute_task(workspace,body,key=None,cancel=None):
 from serve.hydra_lab_benchmarks import now,comparison_key,summary,acquire_runtime_lock,release_runtime_lock,reserve_system_runtime
 import psutil
 if not workspace.lock.acquire(False):raise ValueError('benchmark already running')
 try:lease=acquire_runtime_lock(workspace.store.root)
 except Exception:workspace.lock.release();raise
 key=key or uuid.uuid4().hex;cancel=cancel or threading.Event();folder=workspace.store.root/'runs'/key;folder.mkdir(parents=True);cat=next(r for r in workspace.catalog() if r['id']==body['model_id']);model=Path(cat['assets'][0]['path']);binary=Path(cat['runtime_path']);ground=cat['id'].startswith('mudler/');image_task=cat.get('lab_task')=='image';music_task=cat.get('lab_task')=='music';timeout=600 if music_task else 300 if ground or image_task else 180;child=None;system=None;live_monitor=None;start=time.monotonic()
 row=dict(run_id=key,origin='E2E_TEST',status='RUNNING',timestamp=now(),started_at=now(),model=cat['id'],model_hash=cat['asset_hash'],runtime=str(binary),runtime_hash=cat['runtime_hash'],backend='NOT_VERIFIED' if image_task else 'CPU',quantization=cat['quantization'],profile=cat.get('lab_profile','image-vulkan-v4' if image_task else 'locate-cpu-v4' if ground else 'bonsai-ptq1-cpu-v4'),configuration={'threads':2,'gpu_layers':0,'deadline_s':timeout,'ram_min_free_gib':32,'rss_stop_gib':24 if cat['quantization']=='NVFP4' else 20,'ram_remaining_stop_gib':12,'budget_type':'CONSERVATIVE_ESTIMATE; monitored, not OS hard cap','weight_layout':'native quantized weights; no fp16 conversion requested','workspace_allowance_gib':8,'context':512 if not ground else None},parameters={'task':'music' if music_task else 'image' if image_task else 'grounding' if ground else 'text','samples_requested':body['samples'],'cold_smoke':True,'max_tokens':min(body['max_tokens'],16)},prompt=body['prompt'],prompt_id=body['prompt_id'],prompt_hash=hashlib.sha256(body['prompt'].encode()).hexdigest(),template_hash=cat['asset_hash'],measurement_scope='native_process_end_to_end_including_cold_load',request_json=body,samples=[],warmup=[],summary={},quality_gate='NOT_AVAILABLE',events=[],error=None,exit_code=None,cleanup=False,log_path=str(folder/'runtime.log'),artifacts=str(folder),owner_pid=os.getpid(),owner_created=psutil.Process().create_time(),real_execution_kind='music-generation' if music_task else 'image-generation' if image_task else 'grounding' if ground else 'text-generation-native-CPU')
 row['parameters'].update(max_tokens=body['max_tokens'],thinking=body.get('thinking','auto'))
 row['comparison_key']=comparison_key(row)
 def event(kind,detail=None):row['events'].append(dict(at=now(),monotonic=time.monotonic(),kind=kind,detail=detail));workspace.store.put(row)
 try:
  event('admission')
  if body['profile']!='cpu' or workspace.lab.profile.get('operational_loaded'):row['status']='BLOCKED';raise ValueError('isolated CPU only; operational runtime must remain unloaded')
  system=reserve_system_runtime(Path(__file__).resolve().parents[1]);from serve.hydra_lab_live import LiveMonitor
  live_monitor=LiveMonitor(workspace,row);workspace.lab.stop_backend();row['ram_before']=psutil.virtual_memory().available
  if row['ram_before']<32*1024**3:row['status']='RESOURCE_BLOCKED';raise RuntimeError('32GiB free required for conservative CPU tensor/workspace budget plus OS reserve')
  for path,expected in [(model,cat['asset_hash']),(binary,cat['runtime_hash'])]:
   with path.open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
   if h!=expected:row['status']='BLOCKED';raise ValueError('asset/runtime identity changed')
  for name,expected in cat.get('runtime_manifest',{}).items():
   with (binary.parent/name).open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
   if h!=expected:raise ValueError('isolated runtime dependency changed: '+name)
  row['configuration']['runtime_manifest']=cat.get('runtime_manifest',{})
  row['configuration']['mtp']=False
  if music_task:
   for asset in cat['components']:
    with Path(asset['path']).open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
    if h!=asset['sha256']:raise ValueError('music VAE identity changed')
   request=music_request(body['prompt'])
   (folder/'request.json').write_text(json.dumps(request),encoding='utf-8');row['configuration'].update(request=request,max_seq=1024,vae_core_frames=32,vae_halo_frames=4)
   args=[str(binary),'--model',str(model),'--vae',cat['components'][0]['path'],'--request',str(folder/'request.json'),'--out',str(folder/'song.wav'),'--device','CPU','--max-seq','1024','--vae-core','32','--vae-halo','4','--score',str(folder/'score.abc')]
  elif image_task:
   for asset in cat['components']:
    with Path(asset['path']).open('rb') as f:h=hashlib.file_digest(f,'sha256').hexdigest()
    if h!=asset['sha256']:raise ValueError('pipeline component identity mismatch')
   row['configuration'].update(width=256,height=256,steps=2,seed=42,cfg_scale=1 if cat['id']=='unsloth/Z-Image-Turbo-GGUF' else 6,sampler='euler',weight_placement='CPU mapped; diffusion compute Vulkan, text encoder/VAE CPU')
   args=[str(binary),'--diffusion-model',str(model),'--vae',cat['components'][1]['path'],'--llm',cat['components'][0]['path'],'-p',body['prompt'],'--steps','2','--cfg-scale','1' if cat['id']=='unsloth/Z-Image-Turbo-GGUF' else '6','--sampling-method','euler','-W','256','-H','256','--seed','42','--threads','2','--offload-to-cpu','--clip-on-cpu','--vae-on-cpu','--mmap','--diffusion-fa','-o',str(folder/'generated.png')]
  elif ground:
   from PIL import Image,ImageDraw
   image=Image.new('RGB',(448,448),'white');draw=ImageDraw.Draw(image);draw.rectangle((40,80,190,240),fill='red');draw.ellipse((260,100,400,240),fill='blue');image.save(folder/'input.png');row['input_geometry']={'red_rectangle':[40,80,190,240],'blue_circle':[260,100,400,240],'width':448,'height':448,'synthetic':True}
   args=[str(binary),'detect','--model',str(model),'--input',str(folder/'input.png'),'--prompt',body['prompt'],'--mode','slow','--threads','2','--output',str(folder/'detections.json'),'--annotated',str(folder/'annotated.png')]
  else:
   capabilities=set()
   if body.get('thinking','auto')!='auto':
    from serve.hydra_execution_v10 import guarded_run
    help_result=guarded_run([str(binary),'--help'],cwd=binary.parent,capture_output=True,text=True,timeout=15)
    help_text=(help_result.stdout or '')+(help_result.stderr or '')
    (folder/'runtime-help.txt').write_text(help_text,encoding='utf8')
    if help_result.returncode==0 and all(flag in help_text for flag in ('--reasoning','--single-turn','--conversation')):capabilities.add('reasoning')
    if help_result.returncode==0 and all(flag in help_text for flag in ('--chat-template-kwargs','--reasoning-budget')):capabilities.add('thinking_template')
   args=[str(binary),*text_arguments(model,body,capabilities)]
  row['command']=args;event('startup');env=dict(os.environ,CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',OMP_NUM_THREADS='2');env['GGML_BACKEND_PATH']=str(binary.parent)
  if not image_task:env.pop('GGML_BACKEND_PATH',None) # The native loader expects a backend file, not its directory.
  if image_task:
   env.pop('CUDA_VISIBLE_DEVICES',None);env.pop('HIP_VISIBLE_DEVICES',None);env.pop('ROCR_VISIBLE_DEVICES',None)
  t=time.perf_counter();peak=0
  with (folder/'runtime.log').open('wb') as err,(folder/'output.txt').open('wb') as out:
   child=guarded_popen(args,cwd=binary.parent,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));process=psutil.Process(child.pid);process.cpu_affinity(process.cpu_affinity()[:2]);row['owned_pid']=child.pid;row['owned_created']=process.create_time();event('request_start')
   while child.poll() is None:
    if cancel.is_set():row['status']='CANCELLED';raise RuntimeError('cancelled')
    if time.monotonic()-start>timeout:row['status']='TIMEOUT';raise TimeoutError('absolute native task deadline')
    try:peak=max(peak,process.memory_info().rss)
    except psutil.NoSuchProcess:pass
    if peak>row['configuration']['rss_stop_gib']*1024**3 or psutil.virtual_memory().available<12*1024**3:row['status']='RESOURCE_BLOCKED';raise RuntimeError('monitored resource stop; not OS memory hard cap')
    time.sleep(.1)
  elapsed=(time.perf_counter()-t)*1000;row['exit_code']=child.returncode;row['peak_sampled_rss_bytes']=peak
  if child.returncode:raise RuntimeError('native child returned '+str(child.returncode))
  text=(folder/'output.txt').read_text(encoding='utf-8',errors='replace');log=(folder/'runtime.log').read_text(encoding='utf-8',errors='replace')
  if music_task:
   import wave
   files=list(folder.glob('song*.wav'))
   if len(files)!=1:raise ValueError('music pipeline did not produce exactly one WAV')
   with wave.open(str(files[0])) as wav:frames=wav.getnframes();rate=wav.getframerate();channels=wav.getnchannels();duration=frames/rate
   if frames<=0 or channels!=2 or not 0<duration<=4:raise ValueError('invalid or unbounded music output')
   row['output_validity']={'wav_valid':True,'duration_seconds':duration,'channels':channels,'score_available':(folder/'score.abc').is_file(),'perceptual_quality':'NOT_VERIFIED'};row['audio_metrics']={'audio_seconds':duration,'audio_bytes':files[0].stat().st_size,'cold_real_time_factor':elapsed/1000/duration};row['quality_gate']='VALID_WAV';output=str(files[0])
  elif image_task:
   from PIL import Image
   output_file=folder/'generated.png'
   if not output_file.is_file():
    found=list(folder.glob('generated*.png'))
    if len(found)==1:output_file=found[0]
   with Image.open(output_file) as im:im.load();valid=im.width==256 and im.height==256;shape=[im.width,im.height]
   if not valid:raise ValueError('unexpected generated image dimensions')
   if 'vulkan' not in log.lower() and 'vulkan' not in text.lower():raise ValueError('actual Vulkan backend not attested in logs')
   row['backend']='Vulkan diffusion / CPU text+VAE';row['output_validity']={'image_valid':True,'dimensions':shape,'perceptual_quality':'NOT_VERIFIED'};row['quality_gate']='VALID_IMAGE';output=str(output_file)
  elif ground:
   result=json.loads((folder/'detections.json').read_text());boxes=result.get('detections',[]);valid=[]
   for box in boxes:
    coords=box.get('box',box.get('bbox',[]))
    if isinstance(coords,dict):coords=[coords.get(k) for k in ('x1','y1','x2','y2')]
    if len(coords)!=4 and all(k in box for k in ('x1','y1','x2','y2')):coords=[box[k] for k in ('x1','y1','x2','y2')]
    valid.append(len(coords)==4 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in coords) and 0<=coords[0]<coords[2]<=448 and 0<=coords[1]<coords[3]<=448)
   row['original_result']=result;row['output_validity']={'detections':len(boxes),'coordinates_valid':bool(boxes) and all(valid),'semantic_grounding_quality':'NOT_VERIFIED; synthetic geometry only'}
   row['quality_gate']='VALID_COORDINATES' if row['output_validity']['coordinates_valid'] else 'QUALITY_GATE_FAILED'
   if not row['output_validity']['coordinates_valid']:raise ValueError('grounding produced no valid coordinate set')
   output=json.dumps(result,ensure_ascii=False)
  else:
   if not text.strip():raise ValueError('empty generated output')
   row['output_validity']={'nonempty_text':True,'semantic_quality':'NOT_VERIFIED'};row['quality_gate']='OUTPUT_NONEMPTY';output=text
  native_metrics={}
  if not ground and not image_task and not music_task:
   import re
   for prefix,key in [('prompt eval time','prefill'),('eval time','decode')]:
    found=re.search(r'common_perf_print:\s+'+prefix+r' =\s*([0-9.]+) ms /\s*(\d+) (?:tokens|runs).*?([0-9.]+) tokens per second',log)
    if found:native_metrics.update({key+'_ms':float(found.group(1)),key+'_tps':float(found.group(3)),('prompt_tokens' if key=='prefill' else 'decode_steps'):int(found.group(2))})
  row['samples']=[{'e2e_ms':elapsed,'output':output,'tokens':None,'prefill_tps':None,'decode_tps':None,'ttft_ms':None,'includes_model_load':True,**native_metrics}];row['summary']=summary(row['samples']);event('generation_complete',row['output_validity'])
 except Exception as exc:
  if row['status']=='RUNNING':row['status']='FAIL'
  row['error']=type(exc).__name__+': '+str(exc);event('error',row['error'])
 finally:
  if child and child.poll() is None:
   child.terminate()
   try:child.wait(5)
   except subprocess.TimeoutExpired:child.kill();child.wait(3)
  row['exit_code']=child.returncode if child else None;row['cleanup']=child is None or child.poll() is not None;event('cleanup',{'owned_pid':child.pid if child else None,'confirmed':row['cleanup']})
  if live_monitor:live_monitor.close()
  if system:system.release()
  release_runtime_lock(lease);workspace.lock.release()
 if row['status']=='RUNNING':
  row['status']='PASS' if row['cleanup'] else 'FAIL';event('completed_after_cleanup',{'locks_released':True,'cleanup':row['cleanup']})
 row['finished_at']=now();row['artifact_hashes']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file() and p.suffix in ('.png','.json','.txt','.wav','.abc')};workspace.store.put(row);(folder/'run.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
 if workspace.lab.profile.get('publish_existing_benchmarks'):
  from serve.hydra_lab_integration import publish_existing_registry
  publish_existing_registry(workspace,Path(__file__).resolve().parents[1])
 return row
