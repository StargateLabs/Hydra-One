"""Local CPU audio transcription using the installed Whisper server."""
import io,json,os,socket,subprocess,threading,time,uuid,wave,tempfile
from pathlib import Path
import urllib.request
from serve.whisper_languages import language_inventory
from serve.whisper_options import decoding_options,decoding_flags
MAX_INPUT=20*1024**2

def transcript_segments(result,duration):
 import math
 rows=[]
 for row in result.get('segments',[]) if isinstance(result.get('segments'),list) else []:
  if not isinstance(row,dict):continue
  start=row.get('start');end=row.get('end');text=row.get('text')
  if not isinstance(text,str) or not text.strip() or any(type(value) not in (int,float) or not math.isfinite(value) for value in (start,end)):continue
  if not 0<=start<min(end,duration) or end>duration+.5:continue
  rows.append({'start':start,'end':min(end,duration),'text':text.strip()})
 return sorted(rows,key=lambda row:row['start'])

def subtitle_text(segments,vtt=False):
 def timestamp(seconds):
  ms=round(seconds*1000);hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
  return f'{hours:02d}:{minutes:02d}:{seconds:02d}{"." if vtt else ","}{ms:03d}'
 blocks=[f'{i}\n{timestamp(row["start"])} --> {timestamp(row["end"])}\n{row["text"]}' for i,row in enumerate(segments,1)]
 return ('WEBVTT\n\n' if vtt else '')+'\n\n'.join(blocks)+('\n' if blocks else '')

def validate_wav(data,stereo=False):
 with wave.open(io.BytesIO(data),'rb') as audio:
  duration=audio.getnframes()/audio.getframerate()
  if audio.getnchannels()!=(2 if stereo else 1) or audio.getsampwidth()!=2 or audio.getframerate()!=16000:raise ValueError('Stereo diarization requires original stereo PCM16 at 16 kHz' if stereo else 'Audio must be mono PCM16 at 16 kHz')
  if not 0<duration<=300:raise ValueError('Audio duration must be between 0 and 300 seconds')
  if len(audio.readframes(audio.getnframes()))!=audio.getnframes()*audio.getnchannels()*2:raise ValueError('Truncated WAV audio')
  return duration

class LocalAudio:
 def __init__(self,root):
  self.root=Path(root);self.models=self.root.parent/'Strata-data/models/audio/whisper';self.binary=Path.home()/'.unsloth/whisper.cpp/build/bin/Release/whisper-server.exe'
  self.lock=threading.RLock();self.request_lock=threading.Lock();self.child=None;self.state={'status':'idle','device':'cpu'};self.prefix='/'+uuid.uuid4().hex
 def status(self):
  with self.lock:
   if self.child and self.child.poll() is not None:self.child=None;self.state.update(status='error',error='Audio process stopped')
   result=dict(self.state,installed=self.binary.is_file(),busy=self.request_lock.locked(),models=[{'path':str(p),'name':p.stem,'bytes':p.stat().st_size} for p in self.models.glob('*.bin')],formats=['wav','mp3','flac','m4a','ogg','webm','mp4','mov'],input_limit_bytes=MAX_INPUT,duration_limit_s=300)
   result['decoding_options_supported']=True
   vad_folder=self.models.parent/'vad'
   result['vad_options_supported']=True
   result['diarization_options_supported']=True
   result['vad_models']=[{'path':str(p.resolve()),'name':p.stem,'bytes':p.stat().st_size} for p in vad_folder.glob('*.bin') if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(vad_folder.resolve()) and 0<p.stat().st_size<=32*1024**2]
   result['dtw_models']=[{'path':str(p.resolve()),'name':p.stem,'bytes':p.stat().st_size} for p in self.models.glob('*dtw*.bin') if p.is_file() and not p.is_symlink() and 0<p.stat().st_size<=32*1024**2]
   result['dtw_options_supported']=True
   if result['status']=='loading' and hasattr(self,'load_started'):result['loading_elapsed_seconds']=max(0,time.monotonic()-self.load_started)
   if self.child:
    try:
     import psutil
     result['process_rss_bytes']=psutil.Process(self.child.pid).memory_info().rss
    except (OSError,psutil.Error):pass
   result.update(language_inventory(self.binary))
   return result
 def start(self,payload):
  import psutil
  with self.lock:
   if not self.child and not getattr(self,'candidate_validation',False):
    from serve.local_speech import selected_audio_runtime
    self.binary=selected_audio_runtime(self.root,'whisper.cpp') or Path.home()/'.unsloth/whisper.cpp/build/bin/Release/whisper-server.exe'
   choices=list(self.models.glob('*.bin'))
   if not choices:raise ValueError('No local Whisper model found')
   path=Path(payload.get('model_path') or choices[0]).resolve(strict=True)
   if not path.is_relative_to(self.models.resolve()) or path.suffix!='.bin':raise ValueError('Choose a model from the local audio folder')
   threads=payload.get('threads',2)
   if type(threads) is not int or not 1<=threads<=8:raise ValueError('Use 1–8 audio CPU threads')
   options=decoding_options(payload)
   if options.get('tinydiarize') and 'tdrz' not in path.stem.lower():raise ValueError('Tiny diarization requires an installed tdrz model')
   if options.get('dtw'):
    dtw_model=Path(options['dtw_model']).resolve(strict=True)
    if not dtw_model.is_relative_to(self.models.resolve()) or dtw_model.suffix.lower()!='.bin' or not dtw_model.is_file() or not 0<dtw_model.stat().st_size<=32*1024**2:
     raise ValueError('Choose a DTW timestamp model from the local audio models folder')
    options['dtw_model']=str(dtw_model)
   if options.get('vad'):
    vad_model=Path(options['vad_model']).resolve(strict=True)
    if not vad_model.is_relative_to((self.models.parent/'vad').resolve()) or vad_model.suffix.lower()!='.bin' or not vad_model.is_file() or not 0<vad_model.stat().st_size<=32*1024**2:
     raise ValueError('Choose a VAD model from the local audio VAD folder')
    options['vad_model']=str(vad_model)
   if self.child and self.child.poll() is None:
    if self.state.get('model_path')==str(path) and self.state.get('threads')==threads and self.state.get('decoding_options',decoding_options({}))==options:return self.status()
    raise ValueError('Stop the current audio model first')
   if not self.binary.is_file():raise ValueError('Installed Whisper server unavailable')
   if path.stat().st_size>8*1024**3 or psutil.virtual_memory().available<path.stat().st_size*4+1024**3:raise ValueError('Insufficient RAM for this audio model')
   with socket.socket() as probe:
    if probe.connect_ex(('127.0.0.1',8093))==0:raise ValueError('Audio port already occupied')
   work=self.root/'data/audio-runtime';work.mkdir(parents=True,exist_ok=True);public=work/'public';public.mkdir(exist_ok=True)
   self.prefix='/'+uuid.uuid4().hex;env=dict(os.environ,HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',CUDA_VISIBLE_DEVICES='-1')
   with (work/'worker.log').open('wb') as log:
    self.load_started=time.monotonic()
    self.child=subprocess.Popen([str(self.binary),'-m',str(path),'-ng','-nfa','-t',str(threads),'-l','auto','--host','127.0.0.1','--port','8093','--request-path',self.prefix,'--public',str(public)]+decoding_flags(options),env=env,cwd=work,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   self.state={'status':'loading','device':'cpu','model_path':str(path),'threads':threads,'decoding_options':options,'started_at':time.time()}
   child=self.child;prefix=self.prefix
   threading.Thread(target=self._wait,args=(child,prefix),daemon=True).start()
   return self.status()
 def _wait(self,child,prefix):
  deadline=time.monotonic()+45
  while time.monotonic()<deadline:
   with self.lock:
    if self.child is not child:return
    if child.poll() is not None:self.state.update(status='error',error='Whisper failed; check data/audio-runtime/worker.log');return
   try:
    with urllib.request.urlopen('http://127.0.0.1:8093'+prefix+'/health',timeout=1) as response:ready=json.load(response)
    if ready.get('status')=='ok':
     with self.lock:
      if self.child is child:self.state.update(status='ready',load_seconds=max(0,time.monotonic()-self.load_started))
     return
   except (OSError,ValueError):pass
   time.sleep(.2)
  with self.lock:
   if self.child is child:self.stop();self.state.update(status='error',error='Audio startup timeout')
 def stop(self):
  with self.lock:
   if self.child and self.child.poll() is None:
    self.child.terminate()
    try:self.child.wait(timeout=5)
    except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
   self.child=None;self.state={'status':'idle','device':'cpu'};return self.status()
 def transcribe(self,data,name='audio.wav',language='auto',translate=False,model=None):
  if not isinstance(data,bytes) or not 0<len(data)<=MAX_INPUT:raise ValueError('Audio file exceeds 20 MiB or is empty')
  if language!='auto' and language not in language_inventory(self.binary)['languages']:raise ValueError('Unsupported language selection for this Whisper runtime')
  selected=None
  if model is not None:
   choices=[p for p in self.models.glob('*.bin') if model in (p.stem,str(p.resolve()))]
   if len(choices)!=1:raise ValueError('Requested audio model is not installed')
   selected=str(choices[0].resolve())
   if self.state.get('status')=='ready' and self.state.get('model_path')!=selected:raise ValueError('Unload the current audio model before selecting another')
  selected_name=Path(selected or self.state.get('model_path') or next(iter(self.models.glob('*.bin')),Path(''))).stem
  if selected_name.endswith('.en') and language not in ('auto','en'):raise ValueError('This English-only Whisper model requires Auto or English; choose a multilingual model for other languages')
  suffix=Path(name).suffix.lower()
  if suffix.lstrip('.') not in self.status()['formats']:raise ValueError('Unsupported audio file type')
  if not self.request_lock.acquire(blocking=False):raise RuntimeError('An audio request is already running')
  started=time.perf_counter()
  try:
   if self.status()['status']!='ready':self.start(dict(self.state.get('decoding_options',{}),model_path=selected or self.state.get('model_path'),threads=self.state.get('threads',2)))
   deadline=time.monotonic()+45
   while self.status()['status']!='ready':
    state=self.status()
    if state['status'] in ('idle','error'):raise RuntimeError(state.get('error') or 'Audio request cancelled')
    if time.monotonic()>deadline:raise RuntimeError('Audio readiness timeout')
    time.sleep(.1)
   temp_root=self.root/'data/audio-temp';temp_root.mkdir(parents=True,exist_ok=True)
   with tempfile.TemporaryDirectory(dir=temp_root) as directory:
    converted=data
    stereo=bool(self.state.get('decoding_options',{}).get('diarize'))
    try:duration=validate_wav(data,stereo=stereo)
    except (ValueError,wave.Error,EOFError):
     import imageio_ffmpeg
     source=Path(directory)/('input'+suffix);target=Path(directory)/'converted.wav';source.write_bytes(data)
     result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-i',str(source),'-t','301','-threads','2']+([] if stereo else ['-ac','1'])+['-ar','16000','-c:a','pcm_s16le',str(target)],capture_output=True,timeout=60)
     if result.returncode or not target.exists():raise ValueError('Audio decoding failed')
     converted=target.read_bytes();duration=validate_wav(converted,stereo=stereo)
    boundary='StrataAudio'+uuid.uuid4().hex;parts=[]
    for key,value in {'language':language,'response_format':'verbose_json','translate':'true' if translate else 'false','temperature':'0.0'}.items():parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
    parts.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="input.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()+converted+b'\r\n');parts.append(('--'+boundary+'--\r\n').encode())
    request=urllib.request.Request('http://127.0.0.1:8093'+self.prefix+'/inference',data=b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=180) as response:result=json.load(response)
    text=result.get('text')
    if not isinstance(text,str):raise ValueError('Audio runtime returned no text')
    elapsed=time.perf_counter()-started;report={'text':text.strip(),'device':'cpu','model':Path(self.state['model_path']).stem,'language_requested':language,'translation_to_english':translate,'audio_seconds':duration,'elapsed_seconds':elapsed,'real_time_factor':elapsed/duration}
    report['segments']=transcript_segments(result,duration)
    if self.state.get('decoding_options',{}).get('diarize') or self.state.get('decoding_options',{}).get('tinydiarize') or self.state.get('decoding_options',{}).get('dtw'):report['native_result']=result
    report['srt']=subtitle_text(report['segments']);report['vtt']=subtitle_text(report['segments'],vtt=True)
    with self.lock:self.state['last_result']=report
    return report
  except TimeoutError as error:
   self.stop()
   raise RuntimeError('Audio request timed out; the owned worker was stopped') from error
  finally:self.request_lock.release()
 close=stop


def process_audio(data, name, start=0, duration=60, normalize=False):
    """Bounded local trim/normalize/WAV conversion, without loading any AI model."""
    import math
    import imageio_ffmpeg
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_INPUT:raise ValueError('Audio input exceeds 20 MiB')
    suffix=Path(name).suffix.lower()
    if suffix not in ('.wav','.mp3','.flac','.m4a','.ogg','.webm','.mp4','.mov'):raise ValueError('Unsupported audio input format')
    if type(start) not in (int,float) or not math.isfinite(start) or not 0<=start<=300:raise ValueError('Start must be between 0 and 300 seconds')
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=300:raise ValueError('Duration must be between 0 and 300 seconds')
    if type(normalize) is not bool:raise ValueError('Normalization must be boolean')
    with tempfile.TemporaryDirectory(prefix='strata-audio-edit-') as directory:
        source=Path(directory)/('input'+suffix);target=Path(directory)/'processed.wav';source.write_bytes(data)
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-ss',str(start),'-i',str(source),
            '-t',str(duration),'-threads','2','-vn','-ac','1','-ar','16000']
        if normalize:command+=['-af','loudnorm=I=-16:TP=-1.5:LRA=11']
        command+=['-c:a','pcm_s16le',str(target)]
        result=subprocess.run(command,capture_output=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not target.is_file():raise ValueError('Local audio conversion failed: '+result.stderr.decode('utf-8',errors='replace')[-800:])
        output=target.read_bytes();actual_duration=validate_wav(output)
        return output,{'duration_s':actual_duration,'bytes':len(output),'sample_rate':16000,'channels':1,
            'normalized':normalize,'device':'cpu','format':'pcm_s16le','source_start_s':start}
