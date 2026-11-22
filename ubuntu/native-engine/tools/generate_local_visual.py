"""Diffusers offline worker. No downloads, custom code or pickle model weights."""
import argparse,hashlib,json,os,time,traceback,subprocess
from pathlib import Path

def run(request):
 q=json.loads(request.read_text(encoding='utf-8'))
 if q.get('video_mode')=='image':
  from generate_image_video import run as image_video
  return image_video(request)
 if q.get('video_mode')=='interpolate':
  from interpolate_local_video import run as interpolate
  return interpolate(request)
 import importlib.metadata,inspect,threading
 import torch,psutil
 from PIL import Image
 from diffusers import StableDiffusionPipeline,StableDiffusionXLPipeline,TextToVideoSDPipeline,StableDiffusionImg2ImgPipeline,StableDiffusionXLImg2ImgPipeline,DDIMScheduler,EulerDiscreteScheduler,DPMSolverMultistepScheduler

 q=json.loads(request.read_text(encoding='utf-8'));folder=request.parent;started=time.time();peak=[0];done=threading.Event()
 def sample():
  while not done.wait(.1):peak[0]=max(peak[0],psutil.Process().memory_info().rss)
 threading.Thread(target=sample,daemon=True).start()
 try:
  device=q['device']
  if device=='cuda' and not torch.cuda.is_available():raise ValueError('CUDA is unavailable in the selected runtime')
  torch.set_num_threads(min(8,os.cpu_count() or 1))
  if device=='cuda':
   free,_=torch.cuda.mem_get_info();need=q['source_bytes']*2+q.get('control_model_bytes',0)*3+q.get('image_adapter_bytes',0)*4+q['width']*q['height']*(q['frames'] if q['kind']=='video' else 1)*512+256*1024**2
   if free<need:raise ValueError('Insufficient free GPU memory for conservative estimate')
   torch.cuda.reset_peak_memory_stats()
  classes={c.__name__:c for c in (StableDiffusionPipeline,StableDiffusionXLPipeline,TextToVideoSDPipeline)}
  reference=None;base_family=q['family'].replace('Inpaint','');pipeline=classes[base_family]
  if q.get('image_mode') in ('reference','inpaint'):
   source=(folder/q['input_image']).resolve()
   if not source.is_relative_to(folder.resolve()) or not source.is_file() or source.stat().st_size>8*1024**2:raise ValueError('Invalid local reference image')
   if hashlib.sha256(source.read_bytes()).hexdigest()!=q['input_image_sha256']:raise ValueError('Reference image changed')
   with Image.open(source) as image:
    if image.width*image.height>16*1024**2 or image.width<1 or image.height<1:raise ValueError('Reference image exceeds pixel limit')
    image.load();reference=image.convert('RGB').resize((q['width'],q['height']))
   pipeline={'StableDiffusionPipeline':StableDiffusionImg2ImgPipeline,'StableDiffusionXLPipeline':StableDiffusionXLImg2ImgPipeline}[base_family]
  mask=None
  if q.get('image_mode')=='inpaint':
   from diffusers import StableDiffusionInpaintPipeline,StableDiffusionXLInpaintPipeline
   pipeline={'StableDiffusionPipeline':StableDiffusionInpaintPipeline,'StableDiffusionXLPipeline':StableDiffusionXLInpaintPipeline}[base_family]
   source=(folder/q['input_mask']).resolve()
   if not source.is_relative_to(folder.resolve()) or source.is_symlink() or not source.is_file() or source.stat().st_size>8*1024**2 or hashlib.sha256(source.read_bytes()).hexdigest()!=q['input_mask_sha256']:raise ValueError('Mask changed or invalid')
   with Image.open(source) as image:
    if not 0<image.width*image.height<=16*1024**2:raise ValueError('Mask exceeds pixel limit')
    image.load();mask=image.convert('L').resize((q['width'],q['height']),Image.Resampling.NEAREST)
  control_kwargs={};control_image=None
  if q.get('control_model'):
   from diffusers import ControlNetModel,StableDiffusionControlNetPipeline,StableDiffusionXLControlNetPipeline,StableDiffusionControlNetImg2ImgPipeline,StableDiffusionXLControlNetImg2ImgPipeline
   pipeline=({'StableDiffusionPipeline':StableDiffusionControlNetImg2ImgPipeline,'StableDiffusionXLPipeline':StableDiffusionXLControlNetImg2ImgPipeline} if reference is not None else {'StableDiffusionPipeline':StableDiffusionControlNetPipeline,'StableDiffusionXLPipeline':StableDiffusionXLControlNetPipeline})[base_family]
   if mask is not None:
    from diffusers import StableDiffusionControlNetInpaintPipeline,StableDiffusionXLControlNetInpaintPipeline
    pipeline={'StableDiffusionPipeline':StableDiffusionControlNetInpaintPipeline,'StableDiffusionXLPipeline':StableDiffusionXLControlNetInpaintPipeline}[base_family]
   source=(folder/q['control_image']).resolve()
   if not source.is_relative_to(folder.resolve()) or source.is_symlink() or not source.is_file() or source.stat().st_size>8*1024**2 or hashlib.sha256(source.read_bytes()).hexdigest()!=q['control_image_sha256']:raise ValueError('Control image changed or invalid')
   with Image.open(source) as image:
    if not 0<image.width*image.height<=16*1024**2:raise ValueError('Control image exceeds pixel limit')
    image.load();control_image=image.convert('RGB').resize((q['width'],q['height']))
   control_kwargs['controlnet']=ControlNetModel.from_pretrained(q['control_model'],local_files_only=True,use_safetensors=True,torch_dtype=torch.float32 if device=='cpu' else torch.float16)
  video_reference=None
  if q.get('video_mode')=='reference':
   from diffusers import VideoToVideoSDPipeline
   import numpy as np
   pipeline=VideoToVideoSDPipeline;source=(folder/q['input_video']).resolve()
   if not source.is_relative_to(folder.resolve()) or source.is_symlink() or not source.is_file() or source.stat().st_size>8*1024**2 or hashlib.sha256(source.read_bytes()).hexdigest()!=q['input_video_sha256']:raise ValueError('Reference video changed or invalid')
   result=subprocess.run([q['ffmpeg'],'-nostdin','-hide_banner','-loglevel','error','-protocol_whitelist','file,pipe','-i',str(source),'-vf',f"fps={q['fps']},scale={q['width']}:{q['height']}",'-frames:v',str(q['frames']),'-an','-sn','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],capture_output=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   expected=q['frames']*q['height']*q['width']*3
   if len(result.stdout)!=expected:raise ValueError('Reference video needs at least the selected frame count at the chosen FPS')
   video_reference=list(np.frombuffer(result.stdout,dtype=np.uint8).reshape(q['frames'],q['height'],q['width'],3))
  pipe=pipeline.from_pretrained(q['model'],local_files_only=True,use_safetensors=True,torch_dtype=torch.float32 if device=='cpu' else torch.float16,**control_kwargs).to(device)
  if q.get('image_adapter'):
   adapter=Path(q['image_adapter'])
   if adapter.suffix!='.safetensors' or adapter.is_symlink() or not adapter.is_file() or not 0<adapter.stat().st_size<=256*1024**2:raise ValueError('Invalid image LoRA adapter')
   if hashlib.sha256(adapter.read_bytes()).hexdigest()!=q['image_adapter_sha256']:raise ValueError('Image LoRA adapter changed')
   pipe.load_lora_weights(str(adapter.parent),weight_name=adapter.name,local_files_only=True,use_safetensors=True,adapter_name='strata-local')
   pipe.set_adapters('strata-local',adapter_weights=q['adapter_scale'])
  scheduler=q.get('scheduler','default')
  if scheduler!='default':
   cls={'ddim':DDIMScheduler,'euler':EulerDiscreteScheduler,'dpmpp':DPMSolverMultistepScheduler}[scheduler]
   settings={'algorithm_type':'dpmsolver++'} if scheduler=='dpmpp' else {}
   pipe.scheduler=cls.from_config(pipe.scheduler.config,**settings)
  pipe.enable_attention_slicing();pipe.vae.enable_slicing()
  # Reject truncation instead of silently losing the tail of a prompt.
  for tokenizer in (getattr(pipe,'tokenizer',None),getattr(pipe,'tokenizer_2',None)):
   if tokenizer:
    for text in (q['prompt'],q['negative_prompt']):
     if len(tokenizer(text,truncation=False)['input_ids'])>tokenizer.model_max_length:raise ValueError('Prompt exceeds this model tokenizer context; shorten it')
  kwargs=dict(prompt=q['prompt'],negative_prompt=q['negative_prompt'],width=q['width'],height=q['height'],num_inference_steps=q['steps'],guidance_scale=q['guidance'],generator=torch.Generator(device=device).manual_seed(q['seed']))
  if 'clip_skip' in q:
   if 'clip_skip' not in inspect.signature(pipe.__call__).parameters:raise ValueError('Clip skip is not supported by this installed pipeline')
   kwargs['clip_skip']=q['clip_skip']
  if reference is not None:
   kwargs.pop('width');kwargs.pop('height');kwargs.update(image=reference,strength=q['strength'])
  if mask is not None:kwargs['mask_image']=mask
  if control_image is not None:
   kwargs['controlnet_conditioning_scale']=q['control_scale'];kwargs['control_image' if reference is not None else 'image']=control_image
  if q['kind']=='video':
   kwargs['output_type']='pil'
   if video_reference is not None:
    kwargs.pop('width');kwargs.pop('height');kwargs.update(video=video_reference,strength=q['video_strength'])
   else:kwargs['num_frames']=q['frames']
  with torch.inference_mode():result=pipe(**kwargs)
  if q['kind']=='image':
   media=folder/'image.png';partial=folder/'image.partial.png';result.images[0].save(partial)
   with Image.open(partial) as image:
    image.verify()
   if result.images[0].size!=(q['width'],q['height']):raise ValueError('Unexpected image dimensions')
  else:
   frames=result.frames[0]
   if len(frames)!=q['frames'] or any(frame.size!=(q['width'],q['height']) for frame in frames):raise ValueError('Unexpected video dimensions or frame count')
   media=folder/'video.mp4';partial=folder/'video.partial.mp4'
   raw=b''.join(frame.convert('RGB').tobytes() for frame in frames)
   subprocess.run([q['ffmpeg'],'-nostdin','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f"{q['width']}x{q['height']}",'-r',str(q['fps']),'-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p',str(partial)],input=raw,check=True,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if not 0<partial.stat().st_size<=128*1024**2:raise ValueError('Output exceeds 128 MiB limit')
  partial.replace(media)
  index=Path(q['model'])/'model_index.json'
  report=dict(status='complete',file=media.name,bytes=media.stat().st_size,sha256=hashlib.sha256(media.read_bytes()).hexdigest(),family=q['family'],model=q['model'],model_index_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),options={k:q[k] for k in ('prompt','negative_prompt','seed','width','height','frames','fps','steps','guidance','device','kind')},elapsed_seconds=time.time()-started,peak_rss_bytes=max(peak[0],psutil.Process().memory_info().rss),peak_cuda_bytes=torch.cuda.max_memory_allocated() if device=='cuda' else None,versions={name:importlib.metadata.version(name) for name in ('torch','diffusers','transformers','safetensors')},offline=True,elapsed_scope='Input decoding, pipeline load, inference and encoding; excludes initial Python imports and server queue',source_files=[{'path':str(p.relative_to(q['model'])),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in Path(q['model']).rglob('*') if p.is_file()],measurement_scope='Worker process RSS and torch allocated GPU bytes; excludes driver and server')
  report['scheduler']=type(pipe.scheduler).__name__;report['options']['scheduler']=q.get('scheduler','default');report['pipeline']=type(pipe).__name__;report['options']['image_mode']=q.get('image_mode','text')
  if reference is not None:report['options'].update(strength=q['strength'],input_image=q['input_image'],input_image_sha256=q['input_image_sha256'])
  if q['kind']=='video':report['options']['video_mode']=q.get('video_mode','text')
  if video_reference is not None:report['options'].update(input_video=q['input_video'],input_video_sha256=q['input_video_sha256'],video_strength=q['video_strength'])
  if mask is not None:report['options'].update(input_mask=q['input_mask'],input_mask_sha256=q['input_mask_sha256'])
  if control_image is not None:report['controlnet_source_files']=[{'path':str(p.relative_to(q['control_model'])),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in Path(q['control_model']).rglob('*') if p.is_file()]
  if control_image is not None:report['options'].update(control_model=q['control_model'],control_image=q['control_image'],control_image_sha256=q['control_image_sha256'],control_scale=q['control_scale'])
  if q.get('image_adapter'):report['options'].update(image_adapter=q['image_adapter'],image_adapter_sha256=q['image_adapter_sha256'],adapter_scale=q['adapter_scale'])
  if 'clip_skip' in q:report['options']['clip_skip']=q['clip_skip']
  temporary=folder/'result.partial.json';temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(folder/'result.json')
 finally:done.set()
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True);args=parser.parse_args()
 try:run(args.request)
 except Exception as error:
  (args.request.parent/'result.json').write_text(json.dumps(dict(status='failed',error=str(error))),encoding='utf-8');traceback.print_exc();raise SystemExit(1)
