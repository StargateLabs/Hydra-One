"""Hydra-owned Italian neural voices; credentials remain in the Windows DPAPI store."""
import base64
import json
import math
import os
from pathlib import Path
import re
import urllib.error
import urllib.request
import uuid

PROVIDERS={
 'qwen_cloud':{'models':['0.6B','1.7B'],'host':'https://qwen-qwen3-tts.hf.space'},
 'cartesia':{'models':['sonic-3.6','sonic-3.5'],'host':'https://api.cartesia.ai'},
 'elevenlabs':{'models':['eleven_flash_v2_5','eleven_multilingual_v2','eleven_v4_turbo'],'host':'https://api.elevenlabs.io'}}
VOICE=re.compile(r'[A-Za-z0-9_-]{6,80}')


def load(root):
    from serve.cloud_providers import crypt
    path=Path(root)/'data/neural-voice.dpapi'
    if not path.exists():return {'profiles':{}}
    if path.stat().st_size>32768:raise ValueError('Deposito vocale non valido')
    return json.loads(crypt(path.read_bytes(),False))


def status(root):
    from serve.cloud_providers import LOCK
    with LOCK:state=load(root)
    rows={}
    for name,spec in PROVIDERS.items():
        row=state['profiles'].get(name,{})
        rows[name]={'model':row.get('model',spec['models'][0]),'voice':row.get('voice','Serena' if name=='qwen_cloud' else ''),
                    'consent':row.get('consent',False),'has_key':bool(row.get('api_key')),'models':spec['models'],
                    'key_required':name!='qwen_cloud'}
    return {'providers':rows,'language':'it','microphone_uploaded':False}


def save(root,payload):
    if not isinstance(payload,dict) or set(payload)!={'provider','api_key','model','voice','consent'}:raise ValueError('Campi voce non validi')
    name=payload['provider'];key=payload['api_key'];voice=payload['voice']
    if name not in PROVIDERS or payload['model'] not in PROVIDERS[name]['models']:raise ValueError('Provider o modello non valido')
    if not isinstance(key,str) or len(key)>4096 or any(not 33<=ord(c)<=126 for c in key):raise ValueError('Chiave non valida')
    if name=='qwen_cloud':
        from serve.qwen_cloud import VOICES
        if key or voice not in VOICES:raise ValueError('Seleziona una voce Qwen; nessuna chiave richiesta')
    elif not isinstance(voice,str) or (voice and not VOICE.fullmatch(voice)):raise ValueError('Voce non valida')
    if type(payload['consent']) is not bool:raise ValueError('Consenso non valido')
    from serve.cloud_providers import LOCK,crypt
    with LOCK:
        state=load(root);old=state['profiles'].get(name,{})
        row={k:payload[k] for k in ('model','voice','consent')};row['api_key']=key or old.get('api_key','')
        if name!='qwen_cloud' and row['consent'] and not row['api_key']:raise ValueError('Inserisci prima la chiave nel deposito protetto')
        state['profiles'][name]=row
        path=Path(root)/'data/neural-voice.dpapi';path.parent.mkdir(exist_ok=True)
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        temporary.write_bytes(crypt(json.dumps(state).encode(),True));os.replace(temporary,path)
    return status(root)


def open_request(name,row,path,body=None):
    from serve.cloud_providers import NoRedirect,ProviderUnavailable
    headers={'Content-Type':'application/json','User-Agent':'Hydra-One/1.0 ARA/1.0'}
    if name=='cartesia':headers.update({'Authorization':'Bearer '+row['api_key'],'Cartesia-Version':'2026-08-14'})
    else:headers['xi-api-key']=row['api_key']
    query=urllib.request.Request(PROVIDERS[name]['host']+path,headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:return urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(query,timeout=20)
    except urllib.error.HTTPError as exc:
        code=exc.code;exc.close()
        raise ProviderUnavailable(name+': HTTP '+str(code)+'. Controlla chiave, modello, voce e quota.') from None
    except (urllib.error.URLError,OSError):raise ProviderUnavailable(name+' non raggiungibile.') from None


def catalog(root,name):
    if name not in PROVIDERS:raise ValueError('Provider non valido')
    if name=='qwen_cloud':
        from serve.qwen_cloud import VOICES
        return {'voices':[{'id':name,'name':name,'native_italian':False} for name in VOICES],'has_more':False,'language_filter':'Auto · italiano sperimentale'}
    row=load(root)['profiles'].get(name,{})
    if not row.get('api_key'):raise ValueError('Salva prima la chiave protetta')
    path='/voices?language=it&limit=100' if name=='cartesia' else '/v2/voices?language=it&page_size=100'
    with open_request(name,row,path) as response:raw=response.read(2097153)
    if len(raw)>2097152:raise ValueError('Catalogo oltre il limite')
    result=json.loads(raw);values=result.get('data' if name=='cartesia' else 'voices',[])
    if not isinstance(values,list):raise ValueError('Catalogo non valido')
    voices=[]
    for value in values[:100]:
        identity=value.get('id' if name=='cartesia' else 'voice_id')
        if not isinstance(identity,str) or not VOICE.fullmatch(identity):continue
        native=(value.get('language')=='it' if name=='cartesia' else value.get('labels',{}).get('language') in ('it','italian'))
        voices.append({'id':identity,'name':str(value.get('name') or identity)[:100],'native_italian':native})
    return {'voices':voices,'has_more':bool(result.get('has_more',False)),'language_filter':'it'}


def events(root,payload):
    if not isinstance(payload,dict) or set(payload)!={'provider','input','speed'}:raise ValueError('Richiesta sintesi non valida')
    name=payload['provider'];text=payload['input'];speed=payload['speed']
    if name not in PROVIDERS or not isinstance(text,str) or not 0<len(text)<=2000:raise ValueError('Testo vocale non valido')
    if type(speed) not in (int,float) or not math.isfinite(speed) or not .7<=speed<=1.3:raise ValueError('Velocità non valida')
    if re.search(r'(?:gsk_|sk-|sk_car_|nvapi-)[A-Za-z0-9_-]{12,}|Bearer\s+\S{12,}',text,re.I):raise ValueError('Possibili credenziali nel testo vocale')
    row=load(root)['profiles'].get(name,{})
    if name=='qwen_cloud':
        if speed!=1.:raise ValueError('Qwen demo supporta soltanto velocità nativa 1×')
        from serve.qwen_cloud import synthesize
        pcm=synthesize(row,text)
        for start in range(0,len(pcm),8192):yield {'audio_base64':base64.b64encode(pcm[start:start+8192]).decode('ascii')}
        yield {'done':True}
        return
    if row.get('consent') is not True or not row.get('api_key') or not VOICE.fullmatch(row.get('voice','')):raise ValueError('Provider vocale non configurato o invio testo non autorizzato')
    if name=='cartesia':
        path='/tts/sse';body={'model_id':row['model'],'transcript':text,'voice':{'mode':'id','id':row['voice']},
            'language':'it','output_format':{'container':'raw','encoding':'pcm_s16le','sample_rate':24000},'generation_config':{'speed':speed}}
    else:
        path='/v1/text-to-speech/'+row['voice']+'/stream/with-timestamps?output_format=pcm_24000'
        body={'model_id':row['model'],'text':text,'language_code':'it','voice_settings':{'speed':speed}}
    total=0;completed=False
    with open_request(name,row,path,body) as response:
        while True:
            raw=response.readline(2097153)
            if not raw:break
            if len(raw)>2097152:raise ValueError('Pacchetto vocale oltre il limite')
            line=raw.decode('utf-8').strip()
            if name=='cartesia':
                if not line.startswith('data:'):continue
                line=line[5:].strip()
            if not line:continue
            value=json.loads(line)
            if value.get('error') or value.get('type')=='error':raise ValueError('Sintesi upstream interrotta')
            encoded=value.get('data') if name=='cartesia' and value.get('type')=='chunk' else value.get('audio_base64')
            if encoded:
                pcm=base64.b64decode(encoded,validate=True);total+=len(pcm)
                if len(pcm)%2 or total>24000*2*120:raise ValueError('PCM vocale oltre i limiti')
                yield {'audio_base64':encoded,'alignment':value.get('normalized_alignment') or value.get('alignment')}
            completed=completed or value.get('done') is True or value.get('type')=='done'
    if not total or (name=='cartesia' and not completed):raise ValueError('Stream vocale incompleto')
    yield {'done':True}


def route(handler,svc,path,post=False):
    if path=='/cloud/neural-voice/qwen-ui' and not post:
        if not handler._authorized() or not handler._own_page('Interfaccia Qwen originale'):return True
        from serve.qwen_cloud import UI
        handler.send_response(302);handler.send_header('Location',UI);handler.end_headers();return True
    if path not in ('/cloud/neural-voice','/cloud/neural-voice/save','/cloud/neural-voice/voices','/cloud/neural-voice/stream'):return False
    if not handler._authorized() or not handler._own_page('Voci neurali gestite dalla dashboard locale'):return True
    from serve.cloud_providers import ProviderUnavailable
    streaming=False
    try:
        root=svc.update_center.root
        if not post and path=='/cloud/neural-voice':handler._json(200,status(root));return True
        if not post or not 0<int(handler.headers.get('Content-Length',0))<=16384:raise ValueError('Richiesta oltre il limite')
        payload=json.loads(handler._read_body())
        if path.endswith('/save'):handler._json(200,save(root,payload))
        elif path.endswith('/voices'):
            if not isinstance(payload,dict) or set(payload)!={'provider'}:raise ValueError('Catalogo non valido')
            handler._json(200,catalog(root,payload['provider']))
        elif path.endswith('/stream'):
            source=events(root,payload);first=next(source)
            handler.send_response(200);handler.send_header('Content-Type','application/x-ndjson');handler.send_header('Cache-Control','no-store');handler.send_header('Connection','close');handler.end_headers();handler.close_connection=True;streaming=True
            try:
                handler.wfile.write((json.dumps(first)+'\n').encode());handler.wfile.flush()
                for event in source:handler.wfile.write((json.dumps(event)+'\n').encode());handler.wfile.flush()
            finally:source.close()
        else:raise ValueError('Metodo non valido')
    except (ValueError,OSError,KeyError,TypeError,StopIteration,ProviderUnavailable):
        if streaming:
            try:handler.wfile.write(b'{"error":"Sintesi interrotta"}\n');handler.wfile.flush()
            except OSError:pass
        else:handler._json(400,{'error':{'message':'Voce non disponibile: verifica chiave, consenso testo, voce, modello e quota.'}})
    return True
