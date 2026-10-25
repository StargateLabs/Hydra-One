"""Native offline StableVideoDiffusionPipeline, bounded original image conditioning."""
import hashlib,json,os,subprocess,time
from pathlib import Path

def run(request):
 import torch
 from PIL import Image
 from diffusers import StableVideoDiffusionPipeline
 q=json.loads(request.read_text(encoding='utf-8'));folder=request.parent.resolve();source=(folder/q['input_image']).resolve();started=time.monotonic()
 if source.parent!=folder or source.is_symlink() or not source.is_file() or source.stat().st_size>8*1024**2 or hashlib.sha256(source.read_bytes()).hexdigest()!=q['input_image_sha256']:raise ValueError('Invalid or changed input image')
 with Image.open(source) as original:
  if not 0<original.width*original.height<=16*1024**2:raise ValueError('Image exceeds pixel limit')
  original.load();image=original.convert('RGB').resize((q['width'],q['height']))
 torch.set_num_threads(min(8,os.cpu_count() or 1));device=q['device']
 if device=='cuda':
  if not torch.cuda.is_available():raise ValueError('GPU is unavailable in selected runtime')
  free,_=torch.cuda.mem_get_info()
  if free<q['source_bytes']*2+q['width']*q['height']*q['frames']*512+1024**3:raise ValueError('Insufficient free GPU memory with reserve')
 dtype=torch.float16 if device=='cuda' else torch.float32
 pipe=StableVideoDiffusionPipeline.from_pretrained(q['model'],local_files_only=True,use_safetensors=True,torch_dtype=dtype).to(device)
 generator=torch.Generator(device=device).manual_seed(q['seed'])
 with torch.inference_mode():result=pipe(image=image,width=q['width'],height=q['height'],num_frames=q['frames'],num_inference_steps=q['steps'],min_guidance_scale=q['min_guidance_scale'],max_guidance_scale=q['max_guidance_scale'],fps=q['fps'],motion_bucket_id=q['motion_bucket_id'],noise_aug_strength=q['noise_aug_strength'],decode_chunk_size=q['decode_chunk_size'],generator=generator,output_type='pil')
 frames=result.frames[0]
 if len(frames)!=q['frames'] or any(frame.size!=(q['width'],q['height']) for frame in frames):raise ValueError('Unexpected native video dimensions or frame count')
 partial=folder/'video.partial.mp4';output=folder/'video.mp4'
 try:
  raw=b''.join(frame.convert('RGB').tobytes() for frame in frames)
  subprocess.run([q['ffmpeg'],'-nostdin','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f"{q['width']}x{q['height']}",'-r',str(q['fps']),'-i','pipe:0','-an','-c:v','libx264','-pix_fmt','yuv420p',str(partial)],input=raw,check=True,capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if not 0<partial.stat().st_size<=128*1024**2:raise ValueError('Video exceeds output limit')
  partial.replace(output)
  report={'status':'complete','file':'video.mp4','bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'family':q['family'],'pipeline':'StableVideoDiffusionPipeline','model':q['model'],'model_index_sha256':hashlib.sha256((Path(q['model'])/'model_index.json').read_bytes()).hexdigest(),'elapsed_seconds':time.monotonic()-started,'offline':True,'options':{key:q[key] for key in ('kind','video_mode','width','height','fps','frames','prompt','negative_prompt','seed','steps','guidance','device','input_image_sha256','motion_bucket_id','noise_aug_strength','min_guidance_scale','max_guidance_scale','decode_chunk_size')},'scope':'Native image-conditioned video; prompt and negative prompt are unused; output has no audio'}
  temporary=folder/'result.partial.json';temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(folder/'result.json')
 finally:partial.unlink(missing_ok=True)
