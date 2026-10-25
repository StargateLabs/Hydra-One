"""Bounded local CPU source separation; model and input never leave the host."""
import base64,io,json,os,socket,subprocess,tempfile,threading,time,urllib.request,wave
from pathlib import Path

def stem_seconds(audio,input_seconds):
 with wave.open(io.BytesIO(audio)) as wav:
  if wav.getnchannels() not in (1,2) or wav.getsampwidth()!=2 or wav.getframerate()!=44100:raise ValueError('Invalid HTDemucs output format')
  frames=wav.getnframes();seconds=frames/wav.getframerate()
  if not 0<seconds<=181 or abs(seconds-input_seconds)>.25:raise ValueError('Invalid output duration')
  if len(wav.readframes(frames))!=frames*wav.getnchannels()*2:raise ValueError('Truncated separation output')
  return seconds

def split_audio(source, folder):
 """Write bounded PCM chunks; the model stays loaded between requests."""
 chunks=[]
 with wave.open(str(source),'rb') as reader:
  params=reader.getparams();size=60*params.framerate
  while True:
   pcm=reader.readframes(size)
   if not pcm:break
   target=Path(folder)/f'chunk-{len(chunks)}.wav'
   with wave.open(str(target),'wb') as writer:writer.setparams(params);writer.writeframes(pcm)
   chunks.append((target,len(pcm)/(params.nchannels*params.sampwidth*params.framerate)))
 return chunks

def combine_stems(parts, duration):
 output=io.BytesIO();signature=None
 with wave.open(output,'wb') as writer:
  for audio,seconds in parts:
   stem_seconds(audio,seconds)
   with wave.open(io.BytesIO(audio)) as reader:
    current=(reader.getnchannels(),reader.getsampwidth(),reader.getframerate())
    if signature is None:
     signature=current;writer.setnchannels(current[0]);writer.setsampwidth(current[1]);writer.setframerate(current[2])
    elif signature!=current:raise ValueError('Inconsistent source stem format')
    writer.writeframes(reader.readframes(reader.getnframes()))
 data=output.getvalue();stem_seconds(data,duration);return data

def stem_ids(outputs):
 """The stem set the loaded model actually returned; the variant decides, not a fixed count."""
 if not isinstance(outputs,list) or not outputs:raise ValueError('Expected source stems from the audio runtime')
 names=[]
 for item in outputs:
  if not isinstance(item,dict):raise ValueError('Invalid stem output')
  name=item.get('id')
  if not isinstance(name,str) or not name:raise ValueError('Invalid stem identifier')
  if name in names:raise ValueError('Expected distinct source stems')
  names.append(name)
 return names


class LocalSeparation:
 def __init__(self,root):
  self.root=Path(root);self.models=self.root.parent/'Strata-data/models/audio/separation';self.lock=threading.Lock();self.child=None;self.cancelled=threading.Event();self.state={'status':'idle','device':'cpu'}
 def status(self):
  result=dict(self.state,busy=self.lock.locked(),models=[{'name':p.stem,'path':str(p),'bytes':p.stat().st_size} for p in self.models.glob('htdemucs*.gguf')])
  if result.get('started_at'):result['elapsed_seconds']=time.time()-result['started_at']
  if self.child:
   try:
    import psutil
    result['process_rss_bytes']=psutil.Process(self.child.pid).memory_info().rss
   except (OSError,psutil.Error):pass
  return result
 def stop(self,cancel=True):
  if cancel:self.cancelled.set()
  child=self.child
  if child and child.poll() is None:
   child.terminate()
   try:child.wait(5)
   except subprocess.TimeoutExpired:child.kill();child.wait(5)
  self.child=None
 def run(self,payload):
  import imageio_ffmpeg,psutil
  from serve.gguf_metadata_light import metadata_string
  from serve.audio_library import AudioLibrary
  encoded=payload.get('audio_base64')
  if not isinstance(encoded,str) or len(encoded)>16*1024**2:raise ValueError('Use a WAV up to 12 MiB')
  data=base64.b64decode(encoded,validate=True)
  if not 0<len(data)<=12*1024**2:raise ValueError('Use a WAV up to 12 MiB')
  with wave.open(io.BytesIO(data)) as wav:
   if wav.getnchannels() not in (1,2) or wav.getsampwidth()!=2 or not 8000<=wav.getframerate()<=48000:raise ValueError('Use mono/stereo PCM16 WAV at 8–48 kHz')
   duration=wav.getnframes()/wav.getframerate()
   if not 0<duration<=180 or len(wav.readframes(wav.getnframes()))!=wav.getnframes()*wav.getnchannels()*2:raise ValueError('Use a complete WAV up to 180 seconds')
  registered=self.status()['models'];row=next((r for r in registered if r['path']==payload.get('model_path')),registered[0] if registered else None)
  if not row or (payload.get('model_path') and row['path']!=payload['model_path']):raise ValueError('Choose an installed separation model')
  model=Path(row['path']).resolve();spec=json.loads(metadata_string(model,'audiocpp.model_spec.json') or '{}')
  if spec.get('family')!='htdemucs':raise ValueError('Only HTDemucs is validated in this workflow')
  if psutil.virtual_memory().available<model.stat().st_size*8+2*1024**3:raise ValueError('Insufficient available RAM')
  from serve.local_speech import selected_audio_runtime
  binary=selected_audio_runtime(self.root) or Path.home()/'.unsloth/audio.cpp/audiocpp_server.exe'
  if not binary.is_file():raise ValueError('Local audio.cpp runtime unavailable')
  if not self.lock.acquire(False):raise RuntimeError('Separation already running')
  self.cancelled.clear();started=time.time();self.state={'status':'running','device':'cpu','model':model.stem,'started_at':started}
  try:
   work=self.root/'data/separation-runtime';work.mkdir(parents=True,exist_ok=True)
   with tempfile.TemporaryDirectory(dir=work) as temporary:
    folder=Path(temporary);source=folder/'source.wav';source.write_bytes(data);converted=folder/'input.wav'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-i',str(source),'-ar','44100','-ac','2','-c:a','pcm_s16le',str(converted)],check=True,capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    config={'host':'127.0.0.1','port':port,'backend':'cpu','threads':8,'lazy_load':False,'max_loaded_models':1,'busy_timeout_ms':180000,'min_free_memory_mb':2048,'models':[{'id':'local-separation','family':'htdemucs','task':'sep','mode':'offline','path':str(model)}]}
    (folder/'server.json').write_text(json.dumps(config),encoding='utf-8')
    with (work/'worker.log').open('w',encoding='utf-8') as log:
     self.child=subprocess.Popen([str(binary),'--config',str(folder/'server.json')],stdout=log,stderr=log,env={**os.environ,'CUDA_VISIBLE_DEVICES':'-1','HIP_VISIBLE_DEVICES':'-1','ROCR_VISIBLE_DEVICES':'-1'},creationflags=subprocess.CREATE_NO_WINDOW)
     try:
      deadline=time.monotonic()+20
      while time.monotonic()<deadline:
       if self.cancelled.is_set():raise RuntimeError('Separation cancelled')
       if not self.child or self.child.poll() is not None:raise RuntimeError('Separation runtime stopped')
       try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=2) as response:json.load(response)
        break
       except OSError:time.sleep(.2)
      else:raise RuntimeError('Separation startup timed out')
      chunks=split_audio(converted,folder);parts={}
      self.state.update(chunks_total=len(chunks),chunks_complete=0,input_seconds=duration)
      for index,(chunk,chunk_duration) in enumerate(chunks):
       if self.cancelled.is_set():raise RuntimeError('Separation cancelled')
       self.state.update(current_chunk=index+1)
       request=urllib.request.Request(f'http://127.0.0.1:{port}/v1/tasks/run',data=json.dumps({'model':'local-separation','audio':str(chunk)}).encode(),headers={'Content-Type':'application/json'})
       with urllib.request.urlopen(request,timeout=180) as response:raw=response.read(64*1024**2+1)
       if len(raw)>64*1024**2:raise ValueError('Separation output exceeds limit')
       outputs=json.loads(raw).get('named_audio_outputs',[])
       names=stem_ids(outputs)
       if not parts:parts={name:[] for name in names}
       elif names!=list(parts):raise ValueError('Inconsistent source stems between chunks')
       for item in outputs:
        audio=base64.b64decode(item.get('audio',''),validate=True);stem_seconds(audio,chunk_duration)
        parts[item['id']].append((audio,chunk_duration))
       self.state.update(chunks_complete=index+1)
      if self.cancelled.is_set():raise RuntimeError('Separation cancelled')
      stems=[];batch=[]
      for name,segments in parts.items():
       audio=combine_stems(segments,duration);seconds=stem_seconds(audio,duration)
       batch.append((audio,{'model':model.stem,'device':'cpu','voice':name,'audio_seconds':seconds,'elapsed_seconds':time.time()-started,'operation':{'chunks':len(chunks),'chunk_seconds':60,'method':'sequential-chunks'}}))
       stems.append({'name':name,'audio_seconds':seconds})
      artifacts=AudioLibrary(self.root).save_batch(batch)
      for stem,artifact in zip(stems,artifacts):stem['artifact']=artifact
      result={'model':model.stem,'device':'cpu','stems':stems,'elapsed_seconds':time.time()-started,'input_seconds':duration,'chunks':len(chunks)}
      self.state.update(status='complete',last_result=result);return result
     finally:self.stop(cancel=False)
  except Exception as error:
   self.state.update(status='cancelled' if self.cancelled.is_set() else 'error',error='Separation cancelled' if self.cancelled.is_set() else str(error));raise RuntimeError(self.state['error']) from error
  finally:self.lock.release()
  close=stop
