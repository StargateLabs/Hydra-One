"""Optional official Qwen demo via Hydra. No local model, clone or arbitrary URL."""
import io
import json
import re
import time
import urllib.request
import urllib.parse
import wave

BASE='https://qwen-qwen3-tts.hf.space'
UI='https://huggingface.co/spaces/Qwen/Qwen3-TTS'
VOICES=('Serena','Vivian','Ryan','Aiden','Dylan','Eric','Ono_anna','Sohee','Uncle_fu')
MODELS=('0.6B','1.7B')

def synthesize(row,text):
    from serve.cloud_providers import NoRedirect
    if row.get('consent') is not True:raise ValueError('Consenso Qwen cloud richiesto')
    if row.get('voice') not in VOICES or row.get('model') not in MODELS:raise ValueError('Voce Qwen non valida')
    deadline=time.monotonic()+40
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def request(path,body=None):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Qwen cloud: tempo massimo raggiunto')
        query=urllib.request.Request(BASE+path,data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type':'application/json','User-Agent':'Hydra-One/1.0 ARA/1.0'})
        return opener.open(query,timeout=min(remaining,30))
    # The official demo exposes Auto, not an explicit Italian selector.
    path='/gradio_api/call/generate_custom_voice'
    with request(path,{'data':[text,'Auto',row['voice'],'',row['model']]}) as response:
        raw=response.read(4097)
    if len(raw)>4096:raise ValueError('Risposta Qwen oltre il limite')
    event=json.loads(raw).get('event_id')
    if not isinstance(event,str) or not re.fullmatch(r'[a-f0-9]{32}',event):raise ValueError('Evento Qwen non valido')
    completed=None;kind='';total=0
    with request(path+'/'+event) as response:
        while time.monotonic()<deadline:
            raw=response.readline(65537);total+=len(raw)
            if not raw:break
            if len(raw)>65536 or total>262144:raise ValueError('Evento Qwen oltre il limite')
            line=raw.decode('utf-8').strip()
            if line.startswith('event:'):kind=line[6:].strip()
            elif line.startswith('data:'):
                if kind=='error':raise ValueError('Demo Qwen non disponibile o quota esaurita')
                if kind=='complete':completed=json.loads(line[5:]);break
    if not isinstance(completed,list) or not completed or not isinstance(completed[0],dict):raise ValueError('Qwen non ha restituito audio')
    url=completed[0].get('url');parsed=urllib.parse.urlsplit(url if isinstance(url,str) else '')
    if parsed.scheme!='https' or parsed.netloc!='qwen-qwen3-tts.hf.space' or not parsed.path.startswith('/gradio_api/file=') or parsed.query or parsed.fragment:raise ValueError('Origine audio Qwen non valida')
    with request(parsed.path) as response:raw=response.read(4*1024**2+1)
    if len(raw)>4*1024**2:raise ValueError('Audio Qwen oltre il limite')
    with wave.open(io.BytesIO(raw),'rb') as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()!=24000 or not 0<wav.getnframes()<=24000*60:raise ValueError('Formato Qwen non compatibile')
        frames=wav.getnframes();pcm=wav.readframes(frames)
        if len(pcm)!=frames*2:raise ValueError('Audio Qwen incompleto')
    return pcm
