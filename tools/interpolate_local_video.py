"""Owned FFmpeg minterpolate worker; original input retained, no neural generation."""
import hashlib,json,os,re,subprocess,time
from pathlib import Path

def run(request):
 q=json.loads(request.read_text(encoding='utf-8'));folder=request.parent.resolve();source=(folder/q['input_video']).resolve();started=time.monotonic()
 if source.parent!=folder or source.is_symlink() or not source.is_file() or source.stat().st_size>8*1024**2 or hashlib.sha256(source.read_bytes()).hexdigest()!=q['input_video_sha256']:raise ValueError('Invalid or changed input video')
 partial=folder/'video.partial.mp4';output=folder/'video.mp4'
 filters=f"scale={q['width']}:{q['height']},minterpolate=fps={q['fps']}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
 command=[q['ffmpeg'],'-nostdin','-hide_banner','-loglevel','error','-progress','pipe:1','-nostats','-y','-protocol_whitelist','file,pipe','-threads','2','-filter_threads','2','-i',str(source),'-map','0:v:0','-vf',filters,'-t',str(q['duration']),'-frames:v',str(q['frames']),'-an','-sn','-dn','-c:v','libx264','-pix_fmt','yuv420p','-fs',str(128*1024**2),str(partial)]
 try:
  result=subprocess.run(command,check=True,capture_output=True,timeout=540,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  counts=re.findall(rb'^frame=(\d+)$',result.stdout,re.MULTILINE)
  if not counts or int(counts[-1])<1:raise ValueError('Input too short for motion interpolation')
  q['frames']=int(counts[-1])
  if not 0<partial.stat().st_size<=128*1024**2:raise ValueError('Invalid interpolation output size')
  partial.replace(output)
  report={'status':'complete','file':'video.mp4','bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'family':q['family'],'pipeline':'FFmpeg minterpolate','model':q['model'],'elapsed_seconds':time.monotonic()-started,'offline':True,'options':{key:q[key] for key in ('kind','video_mode','width','height','fps','frames','duration','prompt','negative_prompt','seed','steps','guidance','device','input_video_sha256')},'scope':'Motion interpolation and resizing; first bounded duration, no audio, no neural generation; actual frame count depends on input duration'}
  temporary=folder/'result.partial.json';temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(folder/'result.json')
 finally:partial.unlink(missing_ok=True)
