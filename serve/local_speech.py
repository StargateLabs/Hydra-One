"""CPU speech synthesis through the user's installed audio.cpp binary."""
import base64,io,json,os,socket,subprocess,threading,time,uuid,wave
from pathlib import Path
import urllib.request

def selected_audio_runtime(root,component='audio.cpp'):
 import hashlib
 if component not in ('audio.cpp','whisper.cpp'):raise ValueError('Invalid audio runtime family')
 root=Path(root);registry=root/'data'/('audio-runtime-selection.json' if component=='audio.cpp' else 'whisper-runtime-selection.json')
 if not registry.is_file():return None
 selection=json.loads(registry.read_text(encoding='utf-8')).get('active')
 if not selection:return None
 directory=Path(selection['directory']).resolve();binary=Path(selection['binary']).resolve()
 if selection.get('scope')!=('audio_cpu' if component=='audio.cpp' else 'whisper_cpu') or selection.get('validation',{}).get('task')!=('tts' if component=='audio.cpp' else 'asr') or not directory.is_relative_to((root/'output/updates/candidates').resolve()) or not binary.is_relative_to(directory):raise ValueError('Invalid selected audio runtime')
 for row in selection['files']:
  path=(directory/row['path']).resolve()
  if not path.is_relative_to(directory) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Selected audio runtime has changed')
 if not binary.is_file():raise ValueError('Selected audio server unavailable')
 return binary

class LocalSpeech:
 def __init__(self,root):
  self.root=Path(root);self.models=self.root.parent/'Strata-data/models/audio/tts';self.binary=Path.home()/'.unsloth/audio.cpp/audiocpp_server.exe';self.child=None;self.lock=threading.RLock();self.request_lock=threading.Lock();self.state={'status':'idle','device':'cpu'};self.identity=None;self.voice_cache={}
 def model_choices(self):
  from serve.gguf_metadata_light import metadata_string
  rows=[]
  for path in self.models.glob('*.gguf'):
   stat=path.stat();key=(str(path),stat.st_size,stat.st_mtime_ns)
   if key not in self.voice_cache:
    try:spec=json.loads(metadata_string(path,'audiocpp.model_spec.json') or '{}');self.voice_cache[key]={'voices':spec.get('ui',{}).get('builtin_voices',[]),'family':spec.get('family')}
    except (OSError,ValueError):self.voice_cache[key]={'voices':[],'family':None}
    while len(self.voice_cache)>64:self.voice_cache.pop(next(iter(self.voice_cache)))
   if self.voice_cache[key]['family'] not in ('kokoro_tts','pocket_tts',None):continue
   rows.append({'name':path.stem,'path':str(path),'bytes':stat.st_size,**self.voice_cache[key],'reference_required':self.voice_cache[key]['family']=='pocket_tts'})
  return rows
 def status(self):
  with self.lock:
   if self.child and self.child.poll() is not None:self.state.update(status='error',error='Speech process stopped');self.child=None
   result=dict(self.state,installed=self.binary.is_file(),busy=self.request_lock.locked(),models=self.model_choices())
   if result['status']=='loading' and hasattr(self,'load_started'):result['loading_elapsed_seconds']=max(0,time.monotonic()-self.load_started)
   if self.child:
    try:
     import psutil
     result['process_rss_bytes']=psutil.Process(self.child.pid).memory_info().rss
    except (OSError,psutil.Error):pass
   return result
 def _get(self,path):
  with urllib.request.urlopen('http://127.0.0.1:8094'+path,timeout=3) as response:return json.load(response)
 def start(self,payload):
  import psutil
  with self.lock:
   if not self.child and not getattr(self,'candidate_validation',False):self.binary=selected_audio_runtime(self.root) or Path.home()/'.unsloth/audio.cpp/audiocpp_server.exe'
   models=list(self.models.glob('*.gguf'))
   if not models:raise ValueError('No supported local speech model available')
   if payload.get('model'):
    matches=[p for p in models if payload['model'] in (p.stem,str(p.resolve()))]
    if len(matches)!=1:raise ValueError('Requested speech model is not installed')
    payload={**payload,'model_path':str(matches[0])}
   path=Path(payload.get('model_path') or models[0]).resolve(strict=True)
   if not path.is_relative_to(self.models.resolve()) or path.suffix!='.gguf' or not any(row['path']==str(path) for row in self.model_choices()):raise ValueError('Choose a registered speech model')
   if self.child and self.child.poll() is None:
    if self.state.get('model_path')==str(path):return self.status()
    raise ValueError('Unload the current speech model first')
   if not self.binary.is_file() or psutil.virtual_memory().available<path.stat().st_size*4+2*1024**3:raise ValueError('Speech runtime or available RAM insufficient')
   with socket.socket() as probe:
    if probe.connect_ex(('127.0.0.1',8094))==0:raise ValueError('Speech port occupied')
   from serve.gguf_metadata_light import metadata_string
   spec=json.loads(metadata_string(path,'audiocpp.model_spec.json') or '{}')
   family=spec.get('family')
   if family not in ('kokoro_tts','pocket_tts'):raise ValueError('Unsupported speech model family')
   reference=None
   if family=='pocket_tts':
    reference=self.reference_audio(payload.get('reference_path'))
   self.identity='strata-'+uuid.uuid4().hex;work=self.root/'data/speech-runtime';work.mkdir(parents=True,exist_ok=True)
   config={'host':'127.0.0.1','port':8094,'backend':'cpu','lazy_load':False,'max_loaded_models':1,'busy_timeout_ms':120000,'min_free_memory_mb':2048,'models':[{'id':self.identity,'family':family,'task':'tts','mode':'offline','path':str(path)}]}
   if reference:config['models'][0]['default_voice_preset']={'voice_ref':str(reference)}
   (work/'server.json').write_text(json.dumps(config),encoding='utf-8');env=dict(os.environ,CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
   self.load_started=time.monotonic()
   with (work/'worker.log').open('wb') as log:self.child=(__import__('serve.hydra_execution_v10',fromlist=['guarded_popen']).guarded_popen if getattr(self,'candidate_validation',False) else subprocess.Popen)([str(self.binary),'--config',str(work/'server.json'),'--backend','cpu','--threads','2','--no-ui'],cwd=self.binary.parent,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   self.state={'status':'loading','device':'cpu','model_path':str(path),'model':path.stem,'started_at':time.time(),'voices':[],'family':family,'reference_path':str(reference) if reference else None}
   self.state['voices']={'voices':spec.get('ui',{}).get('builtin_voices',[])};self.state['default_voice']=spec.get('ui',{}).get('default_voice');child=self.child;identity=self.identity
   threading.Thread(target=self._wait,args=(child,identity),daemon=True).start();return self.status()
 def _wait(self,child,identity):
  deadline=time.monotonic()+60
  while time.monotonic()<deadline:
   with self.lock:
    if self.child is not child:return
    if child.poll() is not None:self.state.update(status='error',error='Speech startup failed; check data/speech-runtime/worker.log');return
   try:
    data=self._get('/v1/models')
    if identity in [row.get('id') for row in data.get('data',[])]:
     voices=self._get('/v1/audio/voices?model='+identity)
     with self.lock:
      if self.child is child:self.state.update(status='ready',load_seconds=max(0,time.monotonic()-self.load_started));self.state['reference_voices']=voices
     return
   except (OSError,ValueError):pass
   time.sleep(.2)
  with self.lock:
   if self.child is child:self.stop();self.state.update(status='error',error='Speech startup timeout')
 def stop(self):
  with self.lock:
   if self.child and self.child.poll() is None:
    self.child.terminate()
    try:self.child.wait(timeout=5)
    except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
   self.child=None;self.state={'status':'idle','device':'cpu'};return self.status()
 def reference_audio(self,value):
  if not isinstance(value,str) or not value.strip():raise ValueError('PocketTTS requires a local reference WAV')
  path=Path(value).expanduser()
  if not path.is_absolute() or path.suffix.lower()!='.wav' or path.is_symlink():raise ValueError('Choose an absolute local WAV path')
  path=path.resolve(strict=True)
  if not path.is_file() or path.stat().st_size>10*1024**2:raise ValueError('Reference WAV exceeds 10 MiB')
  data=path.read_bytes()
  with wave.open(io.BytesIO(data)) as audio:
   if audio.getnchannels() not in (1,2) or audio.getsampwidth()!=2 or not 8000<=audio.getframerate()<=48000:raise ValueError('Reference audio must be PCM16 WAV, mono or stereo, 8–48 kHz')
   frames=audio.getnframes();duration=frames/audio.getframerate()
   if len(audio.readframes(frames))!=frames*audio.getnchannels()*2:raise ValueError('Truncated reference WAV')
  if not 1<=duration<=30:raise ValueError('Use a reference WAV between 1 and 30 seconds')
  return path
 def generate(self,payload):
  text=payload.get('input');speed=payload.get('speed',1)
  if not isinstance(text,str) or not text.strip() or len(text)>2000:raise ValueError('Use 1–2000 text characters')
  if type(speed) not in (float,int) or not .5<=speed<=2:raise ValueError('Use speech speed 0.5–2')
  if payload.get('response_format','wav')!='wav':raise ValueError('This local speech runtime supports WAV output')
  if payload.get('language') not in (None,'it','en-us','en-gb','es','fr-fr','hi','ja','pt-br','zh'):raise ValueError('Unsupported speech language')
  if not self.request_lock.acquire(blocking=False):raise RuntimeError('Speech generation already running')
  started=time.perf_counter()
  try:
   if self.status()['status']!='ready' or payload.get('model') or payload.get('model_path'):self.start(payload)
   deadline=time.monotonic()+60
   while self.status()['status']!='ready':
    state=self.status()
    if state['status'] in ('idle','error'):raise RuntimeError(state.get('error') or 'Speech cancelled')
    if time.monotonic()>deadline:raise RuntimeError('Speech readiness timeout')
    time.sleep(.1)
   if self.state.get('family')=='pocket_tts' and payload.get('speed',1)!=1:raise ValueError('PocketTTS uses its default speech rate in this validated workflow')
   voice=payload.get('voice')
   if voice and voice not in self.state.get('voices',{}).get('voices',[]):raise ValueError('Choose a built-in voice declared by the model')
   body={'model':self.identity,'input':text,'response_format':'wav','speed':speed}
   body['voice']=voice or ('if_sara' if payload.get('language')=='it' and 'if_sara' in self.state['voices']['voices'] else self.state.get('default_voice'))
   if self.state.get('family')=='pocket_tts':
    body.pop('voice',None);body.pop('speed',None);body['voice_ref']=str(self.reference_audio(payload.get('reference_path') or self.state.get('reference_path')))
   elif payload.get('language'):body['language']=payload['language']
   request=urllib.request.Request('http://127.0.0.1:8094/v1/audio/speech',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(request,timeout=120) as response:data=response.read(16*1024**2+1)
   if len(data)>16*1024**2:raise ValueError('Generated audio exceeds output limit')
   with wave.open(io.BytesIO(data)) as audio:duration=audio.getnframes()/audio.getframerate();frames=audio.getnframes()
   if frames<=0:raise ValueError('Speech runtime returned empty audio')
   elapsed=time.perf_counter()-started;report={'model':self.state['model'],'device':'cpu','voice':body.get('voice'),'audio_seconds':duration,'elapsed_seconds':elapsed,'audio_base64':base64.b64encode(data).decode(),'mime_type':'audio/wav'}
   from serve.audio_library import AudioLibrary
   try:report['artifact']=AudioLibrary(self.root).save(data,{**report,'language':payload.get('language')})
   except (OSError,ValueError) as error:report['library_error']=str(error)
   with self.lock:self.state['last_result']={k:v for k,v in report.items() if k!='audio_base64'}
   return report
  except TimeoutError as error:
   self.stop()
   raise RuntimeError('Speech request timed out; the owned worker was stopped') from error
  finally:self.request_lock.release()
 close=stop
