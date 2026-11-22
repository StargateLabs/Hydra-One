"""Relay the original audiobook stream; disconnect cancels the native request."""
import json
import math
import re
import socket
import threading
import urllib.error
import urllib.request


def render_payload(payload):
    if not isinstance(payload,dict):raise ValueError('Invia una configurazione audiolibro.')
    chapters=payload.get('chapters')
    if chapters is not None:
        if not isinstance(chapters,list) or not 1<=len(chapters)<=100:raise ValueError('Storia: da 1 a 100 capitoli.')
        clean=[];total=0;count=0
        for chapter in chapters:
            if not isinstance(chapter,dict) or not isinstance(chapter.get('title',''),str) or len(chapter.get('title',''))>200:raise ValueError('Titolo capitolo non valido.')
            spans=chapter.get('spans')
            if not isinstance(spans,list) or not spans:raise ValueError('Inserisci almeno una battuta per capitolo.')
            lines=[]
            for span in spans:
                if not isinstance(span,dict):raise ValueError('Battuta non valida.')
                text=span.get('text');voice=span.get('voice_id');pause=span.get('pause_ms_after',0);speed=span.get('speed')
                if not isinstance(text,str) or (not text.strip() and not pause):raise ValueError('Inserisci testo o pausa nella battuta.')
                total+=len(text);count+=1
                if total>100000 or count>1000:raise ValueError('Storia: massimo 100000 caratteri e 1000 battute.')
                if voice is not None and (not isinstance(voice,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',voice)):raise ValueError('Voce della battuta non valida.')
                if type(pause) is not int or not 0<=pause<=5000:raise ValueError('Pausa: da 0 a 5000 ms.')
                if speed is not None and (type(speed) not in (int,float) or not math.isfinite(speed) or not .25<=speed<=4):raise ValueError('Velocità battuta: da 0.25 a 4.')
                lines.append({'text':text,'voice_id':voice,'pause_ms_after':pause,'speed':speed})
            clean.append({'title':chapter.get('title',''),'spans':lines})
        common=render_payload({key:value for key,value in payload.items() if key not in ('chapters','text')}|{'text':'story'})
        common.pop('text');common['chapters']=clean;return common
    text=payload.get('text')
    if not isinstance(text,str) or not text.strip() or len(text)>100000:raise ValueError('Testo: da 1 a 100000 caratteri.')
    result={'text':text}
    if 'cover_path' in payload:
        cover=payload['cover_path']
        if not isinstance(cover,str) or not re.fullmatch(r'[0-9a-f]{12}\.(?:jpg|jpeg|png)',cover):raise ValueError('Copertina: seleziona un’immagine caricata dal lettore originale.')
        result['cover_path']=cover
    for key in ('default_voice','language'):
        value=payload.get(key)
        if value is not None:
            if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise ValueError('Voce o lingua non valida.')
            result[key]=value
    for key,choices,default in [('format',('m4b','mp3'),'m4b'),('bitrate',('64k','96k','128k','192k','256k','320k'),'128k'),('loudness',(None,'off','acx','podcast'),None)]:
        value=payload.get(key,default)
        if value not in choices:raise ValueError('Opzione audiolibro non valida: '+key)
        result[key]=value
    metadata=payload.get('metadata')
    if metadata is not None:
        if not isinstance(metadata,dict) or any(key not in ('title','author','narrator','year','genre','description') or not isinstance(value,str) or len(value)>2000 for key,value in metadata.items()):raise ValueError('Metadati audiolibro non validi.')
        result['metadata']=metadata
    for key,minimum,maximum,integer in [('line_gap_ms',0,5000,True),('paragraph_gap_ms',0,5000,True),
            ('num_step',1,512,True),('guidance_scale',0,20,False),('position_temperature',0,100,False),
            ('class_temperature',0,100,False),('seed',0,2**32-1,True),('emo_alpha',0,1,False)]:
        if key not in payload:continue
        value=payload[key]
        if type(value) not in ((int,) if integer else (int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:
            raise ValueError('Opzione audiolibro fuori intervallo: '+key)
        result[key]=value
    for key in ('trim_edges','postprocess_output','vary_repeats'):
        if key not in payload:continue
        if not isinstance(payload[key],bool):raise ValueError('Opzione audiolibro booleana non valida: '+key)
        result[key]=payload[key]
    if 'emo_text' in payload:
        if not isinstance(payload['emo_text'],str) or len(payload['emo_text'])>500:raise ValueError('Descrizione emotiva: massimo 500 caratteri.')
        result['emo_text']=payload['emo_text']
    voice_map=payload.get('voice_map')
    if voice_map is not None:
        if not isinstance(voice_map,dict) or not voice_map or len(voice_map)>100:raise ValueError('Mappa voci: da 1 a 100 nomi.')
        for name,profile in voice_map.items():
            if not isinstance(name,str) or not name.strip() or len(name)>100 or '[' in name or ']' in name:raise ValueError('Nome voce non valido.')
            if not isinstance(profile,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',profile):raise ValueError('Profilo della mappa voci non valido.')
        result['voice_map']={name.strip():profile for name,profile in voice_map.items()}
    lexicon=payload.get('lexicon')
    if lexicon is not None:
        if not isinstance(lexicon,dict) or not lexicon or len(lexicon)>500:raise ValueError('Lessico: da 1 a 500 voci.')
        for word,respelling in lexicon.items():
            if not isinstance(word,str) or not word.strip() or len(word)>200:raise ValueError('Termine del lessico: da 1 a 200 caratteri.')
            if not isinstance(respelling,str) or len(respelling)>500:raise ValueError('Pronuncia del lessico: massimo 500 caratteri.')
        result['lexicon']={word.strip():respelling for word,respelling in lexicon.items()}
    emotion=payload.get('emo_vector')
    if emotion is not None:
        if not isinstance(emotion,list) or len(emotion)!=8:raise ValueError('Vettore emotivo: otto valori numerici.')
        for value in emotion:
            if type(value) not in (int,float) or isinstance(value,bool) or not math.isfinite(value) or not 0<=value<=100:raise ValueError('Vettore emotivo: valori fra 0 e 100.')
        result['emo_vector']=[float(value) for value in emotion]
    return result


def forward(handler,client):
    if not client._busy.acquire(blocking=False):raise RuntimeError('Attendi la fine dell’operazione vocale.')
    started=False
    try:
        if not 0<int(handler.headers.get('Content-Length',0))<=1024*1024:raise ValueError('Configurazione audiolibro oltre il limite.')
        incoming=json.loads(handler._read_body())
        resume_id=incoming.get('resume_job_id') if isinstance(incoming,dict) else None
        if isinstance(incoming,dict) and 'resume_job_id' in incoming:
            if set(incoming)!={'resume_job_id'} or not isinstance(resume_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',resume_id):
                raise ValueError('Identificativo ripresa non valido; i parametri restano quelli originali.')
            payload={}
        else:payload=render_payload(incoming)
        request_id=handler.headers.get('X-Strata-Voice-Request','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',request_id):raise ValueError('Identificativo rendering non valido.')
        cancelled=threading.Event();client._render_transfer=(request_id,None,cancelled)
        client._ready()
        route='/longform/render' if 'chapters' in payload else '/audiobook'
        if resume_id:
            raw,_,_=client._request('/audiobook/jobs',timeout=15)
            original=json.loads(raw);jobs=original.get('jobs') if isinstance(original,dict) else None
            if not isinstance(jobs,list) or not any(isinstance(job,dict) and job.get('job_id')==resume_id and job.get('status') in ('failed','cancelled','interrupted') for job in jobs):
                raise ValueError('Il runtime non dichiara questo audiolibro riprendibile.')
            route+='/resume/'+resume_id
        request=urllib.request.Request(client.base_url+route,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Accept':'text/event-stream'})
        try:response=client._opener.open(request,timeout=300)
        except urllib.error.HTTPError as error:
            detail=error.read(65536).decode('utf-8',errors='replace')
            raise RuntimeError('VoiceStudio: '+detail[:1000]) from None
        with response:
            client._render_transfer=(request_id,response,cancelled)
            if cancelled.is_set():return
            if not response.headers.get('x-omnivoice-backend') or not response.headers.get('Content-Type','').startswith('text/event-stream'):raise RuntimeError('Stream originale VoiceStudio non valido.')
            handler.send_response(200);handler.send_header('Content-Type','text/event-stream');handler.send_header('Cache-Control','no-cache');handler.send_header('Connection','close');handler.end_headers();handler.close_connection=True;started=True
            while True:
                if cancelled.is_set():break
                line=response.readline(262145)
                if not line:break
                if len(line)>262144:raise RuntimeError('Evento VoiceStudio oltre il limite.')
                handler.wfile.write(line);handler.wfile.flush()
    except (BrokenPipeError,ConnectionResetError):
        pass  # Closing the original response propagates client disconnect to its render.
    except Exception as error:
        if not started:raise
        try:handler.wfile.write(('data: '+json.dumps({'type':'error','error':str(error)[:1000]})+'\n\n').encode());handler.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
    finally:
        client._render_transfer=None
        client._busy.release()


def cancel(client,payload):
    transfer=getattr(client,'_render_transfer',None)
    if not isinstance(payload,dict) or not transfer or payload.get('request_id')!=transfer[0]:raise ValueError('Nessun rendering attivo per questa richiesta.')
    _,response,event=transfer;event.set()
    if response is not None:
        connection=getattr(getattr(getattr(response,'fp',None),'raw',None),'_sock',None)
        if connection is None:raise RuntimeError('Interruzione dello stream non disponibile: attendi il termine della fase corrente.')
        try:connection.shutdown(socket.SHUT_RDWR)
        except OSError:pass
    return {'ok':True,'cancellation_requested':True}
