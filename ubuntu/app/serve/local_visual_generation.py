"""Offline, owned image/video workers; explicit Diffusers families only."""
import base64,hashlib,json,math,os,re,shutil,subprocess,threading,time,uuid
from pathlib import Path
from serve.configuration import atomic_json
from serve.gpu_lease import GpuLease
from serve.local_export import LocalExport
FAMILIES={'StableVideoDiffusionPipeline':'video','StableDiffusionPipeline':'image','StableDiffusionXLPipeline':'image','TextToVideoSDPipeline':'video','StableDiffusionInpaintPipeline':'image','StableDiffusionXLInpaintPipeline':'image'}
class LocalVisualGeneration(LocalExport):
 def __init__(self,manager):
  super().__init__(manager);self.state_path=self.root/'data/local-visual-last.json';self.state={'status':'idle'}
  self.default_python=Path(getattr(manager,'python_runtime','missing-visual-runtime'))
  try:
   saved=json.loads(self.state_path.read_text(encoding='utf-8'))
   if saved.get('status') in ('complete','failed','cancelled'):self.state=saved
  except (OSError,ValueError):pass
 def python_runtime(self):
  from serve.visual_python_update import selected_python
  native=self.root/'data/visual-runtime'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
  return selected_python(self.root,native if native.is_file() else self.default_python)
 def models(self):
  rows=[]
  for base in (self.root/'models',self.root.parent/'Strata-data/models'):
   if not base.exists():continue
   for index in base.rglob('model_index.json'):
    try:
     family=json.loads(index.read_text(encoding='utf-8')).get('_class_name')
     if family in FAMILIES and all(list((index.parent/component).glob('*.safetensors')) for component in (('unet','vae','image_encoder') if family=='StableVideoDiffusionPipeline' else ('unet','vae','text_encoder'))):
      if not any(p.is_symlink() for p in index.parent.rglob('*')):
       rows.append(dict(path=str(index.parent.resolve()),name=index.parent.name,family=family,kind=FAMILIES[family],test_fixture='visual-untrained-fixture' in index.parts))
       provenance=index.parent/'provenance.json'
       if provenance.is_file() and provenance.stat().st_size<=1024**2:
        info=json.loads(provenance.read_text(encoding='utf-8'));rows[-1].update(license=info.get('license'),repository=info.get('repository'),revision=info.get('revision'))
    except (OSError,ValueError):pass
  return sorted(rows,key=lambda row:(row['test_fixture'],row['name']))
 def control_models(self):
  rows=[]
  for base in (self.root/'models/controlnet',self.root.parent/'Strata-data/models/controlnet'):
   if not base.is_dir() or base.is_symlink():continue
   for config in base.rglob('config.json'):
    try:
     folder=config.parent
     if config.stat().st_size>1024**2 or any(p.is_symlink() for p in folder.rglob('*')):continue
     spec=json.loads(config.read_text(encoding='utf-8'))
     weights=list(folder.glob('*.safetensors'))
     if spec.get('_class_name')=='ControlNetModel' and weights:
      rows.append(dict(path=str(folder.resolve()),name=folder.name,architecture={key:spec.get(key) for key in ('cross_attention_dim','block_out_channels','layers_per_block','down_block_types')},cross_attention_dim=spec.get('cross_attention_dim'),bytes=sum(p.stat().st_size for p in weights)))
    except (OSError,ValueError):continue
  return rows
 def image_adapters(self):
  rows=[]
  for base in (self.root/'models/image-adapters',self.root.parent/'Strata-data/models/image-adapters'):
   if not base.is_dir() or base.is_symlink():continue
   for path in base.rglob('*.safetensors'):
    if not path.is_symlink() and path.resolve().is_relative_to(base.resolve()) and 0<path.stat().st_size<=256*1024**2:
     rows.append(dict(path=str(path.resolve()),name=path.stem))
  return sorted(rows,key=lambda row:row['name'])
 def validate(self,payload):
  if not isinstance(payload,dict):raise ValueError('Expected an object')
  if payload.get('video_mode')=='interpolate':return self.validate_interpolation(payload)
  model=Path(payload.get('model','')).resolve(strict=True)
  if str(model) not in {r['path'] for r in self.models()}:raise ValueError('Choose an installed Diffusers model folder')
  family=json.loads((model/'model_index.json').read_text(encoding='utf-8')).get('_class_name');kind=FAMILIES[family]
  if payload.get('kind',kind)!=kind:raise ValueError('Model family does not match requested media')
  options={'model':str(model),'family':family,'kind':kind,'prompt':payload.get('prompt',''),'negative_prompt':payload.get('negative_prompt',''),'device':payload.get('device','cpu')}
  for name in ('prompt','negative_prompt'):
   if not isinstance(options[name],str) or len(options[name])>2000:raise ValueError('Prompts must contain at most 2000 characters')
  if not options['prompt'].strip() and family!='StableVideoDiffusionPipeline':raise ValueError('Write a prompt')
  if options['device'] not in ('cpu','cuda'):raise ValueError('Choose cpu or cuda')
  for name,default,minimum,maximum in [('width',512,64,1024),('height',512,64,1024),('steps',20,1,80),('frames',8,2,24),('fps',8,1,24),('seed',0,0,2**32-1)]:
   value=payload.get(name,default)
   if type(value) is not int or not minimum<=value<=maximum:raise ValueError(f'{name} must be {minimum}–{maximum}')
   options[name]=value
  if options['width']%8 or options['height']%8:raise ValueError('Dimensions must be multiples of 8')
  if kind=='video' and options['width']*options['height']*options['frames']>512*512*16:raise ValueError('Video pixel budget exceeded')
  guidance=payload.get('guidance',7.5)
  if type(guidance) not in (int,float) or not 0<=guidance<=20:raise ValueError('Guidance must be 0–20')
  options['guidance']=guidance
  mode=payload.get('image_mode','text')
  if mode not in ('text','reference','inpaint') or (kind!='image' and mode!='text'):raise ValueError('Image reference mode requires an image model')
  scheduler=payload.get('scheduler','default')
  if scheduler not in ('default','ddim','euler','dpmpp'):raise ValueError('Choose a supported scheduler')
  options['scheduler']=scheduler
  adapter=payload.get('image_adapter','')
  if adapter:
   if kind!='image' or not isinstance(adapter,str) or adapter not in {row['path'] for row in self.image_adapters()}:raise ValueError('Choose a local image LoRA Safetensors adapter')
   path=Path(adapter);options['image_adapter']=str(path);options['image_adapter_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();options['image_adapter_bytes']=path.stat().st_size
   scale=payload.get('adapter_scale',1.0)
   if type(scale) not in (int,float) or not math.isfinite(scale) or not 0<=scale<=2:raise ValueError('Image LoRA scale must be 0–2')
   options['adapter_scale']=scale
  control=payload.get('control_model','')
  if control:
   row=next((row for row in self.control_models() if row['path']==control),None)
   if kind!='image' or row is None:raise ValueError('Choose an installed local ControlNet model')
   config=model/'unet/config.json'
   if config.stat().st_size>1024**2:raise ValueError('Invalid base model configuration')
   base_config=json.loads(config.read_text(encoding='utf-8'))
   if any(base_config.get(key)!=value for key,value in row['architecture'].items()):raise ValueError('ControlNet architecture does not match the base model')
   encoded=payload.get('control_image_base64');scale=payload.get('control_scale',1.0)
   if not isinstance(encoded,str) or len(encoded)>12*1024**2:raise ValueError('Control image exceeds 8 MiB')
   try:data=base64.b64decode(encoded,validate=True)
   except ValueError:raise ValueError('Invalid control image encoding') from None
   if not 0<len(data)<=8*1024**2 or not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or data[:4]==b'RIFF' and data[8:12]==b'WEBP'):raise ValueError('Choose a PNG/JPG/WebP control image up to 8 MiB')
   if type(scale) not in (int,float) or not math.isfinite(scale) or not 0<=scale<=2:raise ValueError('Control strength must be 0–2')
   options.update(control_model=control,control_model_bytes=row['bytes'],control_image_base64=encoded,control_image_sha256=hashlib.sha256(data).hexdigest(),control_scale=scale)
  clip_skip=payload.get('clip_skip')
  if clip_skip is not None:
   if (kind!='image' and payload.get('video_mode')!='reference') or type(clip_skip) is not int or not 1<=clip_skip<=12:raise ValueError('Clip skip requires an image model and an integer 1–12')
   options['clip_skip']=clip_skip
  if 'Inpaint' in family and mode!='inpaint':raise ValueError('This inpainting model requires an image and mask')
  options['image_mode']=mode
  if mode in ('reference','inpaint'):
   encoded=payload.get('image_base64');strength=payload.get('strength',.75)
   if not isinstance(encoded,str) or len(encoded)>12*1024**2:raise ValueError('Reference image exceeds 8 MiB')
   try:data=base64.b64decode(encoded,validate=True)
   except ValueError:raise ValueError('Invalid reference image encoding') from None
   signature=data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or len(data)>=12 and data[:4]==b'RIFF' and data[8:12]==b'WEBP'
   if not 0<len(data)<=8*1024**2 or not signature:raise ValueError('Choose a PNG, JPG or WebP reference image up to 8 MiB')
   if type(strength) not in (int,float) or not math.isfinite(strength) or not 0<strength<=1 or int(options['steps']*strength)<1:
    raise ValueError('Image transformation strength must be in (0, 1] and allow at least one generation step')
   options.update(image_base64=encoded,strength=strength,input_image_sha256=hashlib.sha256(data).hexdigest())
  if mode=='inpaint':
   encoded=payload.get('mask_base64')
   if not isinstance(encoded,str) or len(encoded)>12*1024**2:raise ValueError('Mask exceeds 8 MiB')
   try:data=base64.b64decode(encoded,validate=True)
   except ValueError:raise ValueError('Invalid mask encoding') from None
   if not 0<len(data)<=8*1024**2 or not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or data[:4]==b'RIFF' and data[8:12]==b'WEBP'):raise ValueError('Choose a PNG/JPG/WebP mask up to 8 MiB')
   options.update(mask_base64=encoded,input_mask_sha256=hashlib.sha256(data).hexdigest())
  if family=='StableVideoDiffusionPipeline':
   if payload.get('video_mode')!='image':raise ValueError('Stable Video Diffusion requires an input image')
   return self.validate_image_video(payload,options)
  video_mode=payload.get('video_mode','text')
  if video_mode not in ('text','reference') or kind!='video' and video_mode!='text':raise ValueError('Video reference requires a video model')
  options['video_mode']=video_mode
  if video_mode=='reference':
   encoded=payload.get('video_base64');strength=payload.get('video_strength',.6)
   if not isinstance(encoded,str) or len(encoded)>12*1024**2:raise ValueError('Reference video exceeds 8 MiB')
   try:data=base64.b64decode(encoded,validate=True)
   except ValueError:raise ValueError('Invalid video encoding') from None
   if not 0<len(data)<=8*1024**2 or not (data[4:8]==b'ftyp' or data.startswith(b'\x1aE\xdf\xa3')):raise ValueError('Choose an MP4 or WebM reference up to 8 MiB')
   if type(strength) not in (int,float) or not math.isfinite(strength) or not 0<strength<=1 or int(options['steps']*strength)<1:raise ValueError('Video strength requires at least one effective step')
   options.update(video_base64=encoded,video_strength=strength,input_video_sha256=hashlib.sha256(data).hexdigest())
  return options
 def validate_image_video(self,payload,options):
  encoded=payload.get('video_image_base64')
  if not isinstance(encoded,str) or len(encoded)>12*1024**2:raise ValueError('Input image exceeds 8 MiB')
  data=base64.b64decode(encoded,validate=True)
  if not 0<len(data)<=8*1024**2 or not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or data[:4]==b'RIFF' and data[8:12]==b'WEBP'):raise ValueError('Choose PNG/JPG/WebP up to 8 MiB')
  options.update(prompt='',negative_prompt='',guidance=0,video_mode='image',image_base64=encoded,input_image_sha256=hashlib.sha256(data).hexdigest())
  for key,default,low,high in [('motion_bucket_id',127,0,255),('decode_chunk_size',1,1,8)]:
   value=payload.get(key,default)
   if type(value) is not int or not low<=value<=high:raise ValueError(f'{key} must be {low}–{high}')
   options[key]=value
  for key,default,low,high in [('noise_aug_strength',.02,0,1),('min_guidance_scale',1.,0,20),('max_guidance_scale',3.,0,20)]:
   value=payload.get(key,default)
   if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError(f'{key} must be finite in {low}–{high}')
   options[key]=value
  if options['min_guidance_scale']>options['max_guidance_scale']:raise ValueError('Minimum guidance exceeds maximum guidance')
  if any(payload.get(key) for key in ('clip_skip','control_model','image_adapter')) or payload.get('scheduler','default')!='default':raise ValueError('SVD uses its native scheduler and image conditioning')
  return options
 def validate_interpolation(self,payload):
  if payload.get('kind')!='video':raise ValueError('Interpolation requires a video input')
  encoded=payload.get('video_base64')
  if not isinstance(encoded,str) or len(encoded)>12*1024**2:raise ValueError('Video exceeds 8 MiB')
  data=base64.b64decode(encoded,validate=True)
  if not 0<len(data)<=8*1024**2 or not (data[4:8]==b'ftyp' or data.startswith(b'\x1aE\xdf\xa3')):raise ValueError('Choose MP4/WebM up to 8 MiB')
  options=dict(kind='video',video_mode='interpolate',family='FFmpegMotionInterpolation',model='FFmpeg · minterpolate',device='cpu',video_base64=encoded,input_video_sha256=hashlib.sha256(data).hexdigest(),prompt='',negative_prompt='',seed=0,steps=0,guidance=0)
  for name,default,minimum,maximum in [('width',512,64,1024),('height',512,64,1024),('fps',24,2,60),('duration',5,1,10)]:
   value=payload.get(name,default)
   if type(value) is not int or not minimum<=value<=maximum:raise ValueError(f'{name} must be {minimum}–{maximum}')
   options[name]=value
  if options['width']%8 or options['height']%8:raise ValueError('Dimensions must be multiples of 8')
  if options['width']*options['height']*options['fps']*options['duration']>512*512*300:raise ValueError('Interpolation pixel budget exceeded')
  options['frames']=options['fps']*options['duration']
  return options
 def preflight(self,payload):
  import psutil
  options=self.validate(payload);model=Path(options['model']);interpolate=options.get('video_mode')=='interpolate';size=0 if interpolate else sum(p.stat().st_size for p in model.rglob('*') if p.is_file());available=psutil.virtual_memory().available
  runtime=Path(__import__('sys').executable) if interpolate else self.python_runtime()
  reasons=[]
  if not runtime.is_file():reasons.append('Diffusers Python runtime unavailable')
  estimate=size*3+options.get('control_model_bytes',0)*3+options.get('image_adapter_bytes',0)*4+options['width']*options['height']*(options['frames'] if options['kind']=='video' else 1)*512+512*1024**2
  if available<estimate:reasons.append('Insufficient RAM for conservative estimate')
  if shutil.disk_usage(self.root).free<512*1024**2:reasons.append('Keep at least 512 MiB disk space free')
  import imageio_ffmpeg
  options['ffmpeg']=imageio_ffmpeg.get_ffmpeg_exe()
  return dict(options,ready=not reasons,reasons=reasons,python=str(runtime),source_bytes=size,estimated_ram_bytes=estimate,available_ram_bytes=available,estimate_scope='Conservative host RAM estimate; CUDA capacity checked by worker')
 def start(self,payload,operational_idle=True):
  with self.lock:
   if self.status()['status']=='running':raise ValueError('Visual generation already running')
   if not operational_idle or self.manager.status()['status']!='idle':raise ValueError('Unload inference models before visual generation')
   plan=self.preflight(payload)
   if not plan['ready']:raise ValueError('; '.join(plan['reasons']))
   self.lease=GpuLease(self.root,'local-visual').acquire()
   try:
    folder=self.root/'output/visual-generations'/uuid.uuid4().hex;folder.mkdir(parents=True)
    encoded=plan.pop('image_base64',None)
    if encoded is not None:
     source=folder/'input-image';source.write_bytes(base64.b64decode(encoded,validate=True));plan['input_image']=source.name
    encoded_control=plan.pop('control_image_base64',None)
    if encoded_control is not None:
     source=folder/'control-image';source.write_bytes(base64.b64decode(encoded_control,validate=True));plan['control_image']=source.name
    encoded_mask=plan.pop('mask_base64',None)
    if encoded_mask is not None:
     source=folder/'input-mask';source.write_bytes(base64.b64decode(encoded_mask,validate=True));plan['input_mask']=source.name
    encoded_video=plan.pop('video_base64',None)
    if encoded_video is not None:
     source=folder/'input-video';source.write_bytes(base64.b64decode(encoded_video,validate=True));plan['input_video']=source.name
    atomic_json(folder/'request.json',plan)
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    if plan['device']=='cpu':env.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
    with (folder/'worker.log').open('wb') as stream:self.process=subprocess.Popen([plan['python'],'-X','utf8',str(self.root/'tools/generate_local_visual.py'),'--request',str(folder/'request.json')],cwd=self.root,env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    from serve.winjob import contain
    contain(self.process)
    self.state=dict(status='running',id=folder.name,folder=str(folder),device=plan['device'],started_at=time.time(),plan=plan)
    threading.Thread(target=self._watch,args=(self.process,),daemon=True).start()
   except BaseException:
    self.lease.release();self.lease=None;raise
   return self.status()
 def _watch(self,process):
  try:process.wait(timeout=600)
  except subprocess.TimeoutExpired:
   with self.lock:
    if self.process is process:
     self.stop();self.state['error']='Generation exceeded the 600-second limit';atomic_json(self.state_path,self.state)
  with self.lock:
   if self.process is process:self.status()
 def status(self):
  with self.lock:
   if self.process and self.process.poll() is not None:
    code=self.process.returncode;folder=Path(self.state['folder']);report={}
    try:
     report=json.loads((folder/'result.json').read_text(encoding='utf-8'));media=folder/report['file']
     valid=code==0 and report.get('status')=='complete' and media.parent==folder and media.is_file() and 0<media.stat().st_size<=128*1024**2 and report['bytes']==media.stat().st_size and hashlib.sha256(media.read_bytes()).hexdigest()==report['sha256']
    except (OSError,ValueError,KeyError,TypeError):valid=False
    self.state.update(status='cancelled' if self.state.get('cancel_requested') else 'complete' if valid else 'failed',result=report,returncode=code,finished_at=time.time())
    if not valid:self.state['error']=report.get('error','Worker failed or artifact integrity check failed; inspect worker.log')
    self.process=None
    for partial in folder.glob('*.partial*'):partial.unlink(missing_ok=True)
    try:
     self.state_path.parent.mkdir(parents=True,exist_ok=True);atomic_json(self.state_path,self.state)
    except OSError as error:self.state['persistence_error']=str(error)
    finally:
     if self.lease:self.lease.release();self.lease=None
   result=dict(self.state,busy=self.process is not None,supported_families=FAMILIES,image_modes=['text','reference','inpaint'],video_modes=['text','reference','image'],interpolation_supported=True,schedulers=['default','ddim','euler','dpmpp'],clip_skip_supported=True,image_adapters=self.image_adapters(),control_models=self.control_models(),runtime=str(self.python_runtime()),models=self.models())
   if self.process:
    import psutil
    try:result['process_rss_bytes']=psutil.Process(self.process.pid).memory_info().rss
    except psutil.Error:pass
    result['elapsed_seconds']=time.time()-self.state['started_at']
   return result
 def artifact(self,identifier):
  if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):raise ValueError('Invalid artifact id')
  folder=self.root/'output/visual-generations'/identifier
  if folder.is_symlink() or not folder.resolve().is_relative_to((self.root/'output/visual-generations').resolve()):raise ValueError('Invalid artifact folder')
  report=json.loads((folder/'result.json').read_text(encoding='utf-8'));name=report.get('file','')
  if name not in ('image.png','video.mp4') or report.get('status')!='complete':raise ValueError('Artifact unavailable')
  media=folder/name
  if media.is_symlink() or not media.resolve().is_relative_to(folder.resolve()):raise ValueError('Invalid artifact path')
  if not media.is_file() or media.stat().st_size!=report['bytes'] or hashlib.sha256(media.read_bytes()).hexdigest()!=report['sha256']:raise ValueError('Artifact integrity check failed')
  return media
 cancel=LocalExport.stop
