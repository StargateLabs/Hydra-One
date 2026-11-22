"""Groq speech owned by Hydra; encrypted key, explicit text egress, no microphone upload."""
from pathlib import Path
import json,os,uuid,io,wave,re
from serve.cloud_providers import crypt,request,ProviderUnavailable,LOCK
MODELS={
 'canopylabs/orpheus-v1-english':{'language':'en','voices':['autumn','diana','hannah','austin','daniel','troy']},
 'canopylabs/orpheus-arabic-saudi':{'language':'ar','voices':['lulwa','noura','aisha','abdullah','fahad','sultan']}}
def load(root):
 path=Path(root)/'data/groq-voice.dpapi'
 if not path.exists():return {'model':'canopylabs/orpheus-v1-english','voice':'hannah','consent':False,'api_key':''}
 if path.stat().st_size>16384:raise ValueError('Deposito voce non valido')
 return json.loads(crypt(path.read_bytes(),False))
def status(root):
 with LOCK:state=load(root)
 return {k:state[k] for k in ('model','voice','consent')}|{'has_key':bool(state.get('api_key')),'models':MODELS,'languages':['en','ar'],'italian_supported':False,'microphone_uploaded':False}
def save(root,payload):
 if not isinstance(payload,dict) or set(payload)!={'api_key','model','voice','consent'}:raise ValueError('Campi voce Groq non validi')
 key=payload['api_key'];model=payload['model']
 if not isinstance(key,str) or len(key)>4096 or any(ord(c)<33 or ord(c)>126 for c in key):raise ValueError('Chiave Groq non valida')
 if not isinstance(model,str) or model not in MODELS or payload['voice'] not in MODELS[model]['voices'] or type(payload['consent']) is not bool:raise ValueError('Modello, voce o consenso non validi')
 with LOCK:
  state=load(root);state={**payload,'api_key':key or state.get('api_key','')}
  if state['consent'] and not state['api_key']:raise ValueError('Inserisci la chiave Groq nel campo protetto')
  path=Path(root)/'data/groq-voice.dpapi';path.parent.mkdir(exist_ok=True)
  temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(crypt(json.dumps(state).encode(),True));os.replace(temp,path)
 return status(root)
def speech(root,payload):
 if not isinstance(payload,dict) or set(payload)!={'input'} or not isinstance(payload['input'],str) or not 0<len(payload['input'])<=200:raise ValueError('Groq Orpheus richiede 1–200 caratteri per richiesta')
 with LOCK:state=load(root)
 if state.get('consent') is not True or not state.get('api_key'):raise ValueError('Voce Groq non autorizzata o chiave assente')
 if re.search(r'(?:gsk_|sk-|nvapi-)[A-Za-z0-9_-]{12,}|Bearer\s+\S{12,}',payload['input'],re.I):raise ValueError('Il testo vocale contiene possibili credenziali')
 profile={'base_url':'https://api.groq.com/openai/v1','api_key':state['api_key']}
 with request(profile,'/audio/speech',{'model':state['model'],'voice':state['voice'],'input':payload['input'],'response_format':'wav'}) as response:raw=response.read(8388609)
 if len(raw)>8388608:raise ValueError('Audio Groq oltre il limite')
 with wave.open(io.BytesIO(raw),'rb') as wav:
  channels=wav.getnchannels();rate=wav.getframerate();declared=wav.getnframes()
  if wav.getsampwidth()!=2 or channels not in (1,2) or not 8000<=rate<=96000:raise ValueError('WAV Groq non valido')
  # Groq streaming WAV uses UINT32_MAX for data size; validate physical PCM instead.
  streaming=declared*channels*2>=0xfffffff0
  if not streaming and not 0<declared<=rate*60:raise ValueError('Durata WAV Groq non valida')
  pcm=wav.readframes(rate*60+1)
  if not pcm or len(pcm)%(channels*2) or len(pcm)>rate*60*channels*2:raise ValueError('PCM Groq oltre i limiti')
  if not streaming and len(pcm)!=declared*channels*2:raise ValueError('WAV Groq incompleto')
 normalized=io.BytesIO()
 with wave.open(normalized,'wb') as wav:
  wav.setnchannels(channels);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm)
 return normalized.getvalue()
def route(handler,svc,path,post=False):
 from serve.ara_vibevoice import route as vibe_route
 if vibe_route(handler,svc,path,post):return True
 from serve.ara_history import route as history_route
 if history_route(handler,svc,path,post):return True
 from serve.neural_voice import route as neural_route
 if neural_route(handler,svc,path,post):return True
 from serve.groq_transcription import route as transcription_route
 if transcription_route(handler,svc,path,post):return True
 if path not in ('/cloud/voice','/cloud/voice/save','/cloud/voice/speech'):return False
 if not handler._authorized() or not handler._own_page('Voce Groq gestita dalla dashboard locale'):return True
 try:
  root=svc.update_center.root
  if not post:
   if path!='/cloud/voice':raise ValueError('Metodo non valido')
   handler._json(200,status(root));return True
  if not 0<int(handler.headers.get('Content-Length',0))<=8192:raise ValueError('Richiesta voce oltre i limiti')
  payload=json.loads(handler._read_body())
  if path=='/cloud/voice/save':handler._json(200,save(root,payload))
  elif path=='/cloud/voice/speech':
   raw=speech(root,payload);handler.send_response(200);handler.send_header('Content-Type','audio/wav');handler.send_header('Content-Length',str(len(raw)));handler.send_header('Cache-Control','no-store');handler.end_headers();handler.wfile.write(raw)
  else:raise ValueError('Metodo non valido')
 except ProviderUnavailable as exc:handler._json(502,{'error':{'message':str(exc)}})
 except (ValueError,OSError,KeyError,TypeError,wave.Error):handler._json(400,{'error':{'message':'Voce Groq non disponibile: controlla chiave, consenso, modello e quota. Solo inglese/arabo.'}})
 return True
