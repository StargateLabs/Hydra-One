"""Read and operate original queues; never delete projects or job history."""
import json
import re
import base64
from urllib.parse import quote
from pathlib import Path

GROUPS={'jobs':'/jobs?limit=100','batch':'/batch/jobs?limit=100','longform':'/longform/jobs?limit=100','resumable':'/audiobook/jobs','projects':'/projects'}

def activities(client):
    client._ready();result=[]
    for kind,route in GROUPS.items():
        raw,_,_=client._request(route,timeout=15)
        value=json.loads(raw);rows=value if isinstance(value,list) else value.get('jobs') if isinstance(value,dict) else None
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise RuntimeError('Elenco attività VoiceStudio non valido.')
        result.append({'kind':kind,'jobs':rows})
    return {'groups':result}

def action(client,payload):
    if not isinstance(payload,dict):raise ValueError('Attività non valida.')
    identifier=payload.get('id');kind=payload.get('kind');operation=payload.get('action')
    if kind=='audiobook' and operation=='cover':
        name=payload.get('file_name');encoded=payload.get('file_base64')
        if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or Path(name).suffix.lower() not in ('.jpg','.jpeg','.png'):
            raise ValueError('Seleziona una copertina JPG o PNG.')
        if not isinstance(encoded,str) or len(encoded)>12*1024*1024:raise ValueError('Copertina oltre 8 MiB.')
        try:data=base64.b64decode(encoded,validate=True)
        except ValueError:raise ValueError('Copertina codificata non valida.') from None
        valid=data.startswith(b'\x89PNG\r\n\x1a\n') if name.lower().endswith('.png') else data.startswith(b'\xff\xd8\xff')
        if not 0<len(data)<=8*1024*1024 or not valid:raise ValueError('Copertina vuota, oltre 8 MiB o formato non valido.')
        from serve.voicestudio_profiles import _multipart
        body,content_type=_multipart({},(data,'cover'+Path(name).suffix.lower()),'cover')
        if not client._busy.acquire(blocking=False):raise RuntimeError('Attendi la fine dell’operazione vocale.')
        try:
            client._ready();raw,_,_=client._request('/audiobook/cover',None,raw_body=body,content_type=content_type,timeout=30)
            value=json.loads(raw);path=value.get('path') if isinstance(value,dict) else None
            token=path.replace('\\','/').rsplit('/',1)[-1] if isinstance(path,str) else ''
            if not re.fullmatch(r'[0-9a-f]{12}\.(?:jpg|jpeg|png)',token):raise RuntimeError('Copertina originale non confermata.')
            return {'ok':True,'cover_path':token}
        finally:client._busy.release()
    if kind=='audiobook' and operation=='import':
        name=payload.get('file_name');encoded=payload.get('file_base64')
        if not isinstance(name,str) or '/' in name or '\\' in name or Path(name).suffix.lower() not in ('.txt','.md','.epub','.pdf'):raise ValueError('Seleziona un manoscritto TXT, MD, EPUB o PDF.')
        if not isinstance(encoded,str) or len(encoded)>28*1024*1024:raise ValueError('Manoscritto oltre 20 MiB.')
        try:data=base64.b64decode(encoded,validate=True)
        except ValueError:raise ValueError('Manoscritto codificato non valido.') from None
        if not 0<len(data)<=20*1024*1024:raise ValueError('Manoscritto vuoto o oltre 20 MiB.')
        from serve.voicestudio_profiles import _multipart
        raw_body,content_type=_multipart({},(data,'book'+Path(name).suffix.lower()),'file')
        client._ready();raw,_,_=client._request('/audiobook/import',None,raw_body=raw_body,content_type=content_type,timeout=60)
        result=json.loads(raw)
        if not isinstance(result,dict) or not isinstance(result.get('text'),str) or len(result['text'])>100000:raise RuntimeError('Manoscritto oltre il limite dell’editor: massimo 100000 caratteri.')
        return {'ok':True,'result':result}
    if kind=='batch' and operation=='enqueue':
        name=payload.get('file_name');encoded=payload.get('file_base64');langs=payload.get('langs');voice=payload.get('voice_id');preserve=payload.get('preserve_bg',True)
        if payload.get('translation_provider','argos')!='argos':raise ValueError('Questo percorso usa soltanto la traduzione locale Argos.')
        if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or Path(name).suffix.lower() not in ('.mp4','.mov','.mkv','.webm','.avi'):raise ValueError('Seleziona un video locale supportato.')
        if not isinstance(langs,list) or not 1<=len(langs)<=12 or any(not isinstance(lang,str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z]{2,4})?',lang) for lang in langs):raise ValueError('Seleziona da 1 a 12 lingue valide.')
        if not isinstance(preserve,bool):raise ValueError('Conservazione sottofondo non valida.')
        if voice is not None and (not isinstance(voice,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',voice)):raise ValueError('Voce del batch non valida.')
        if not isinstance(encoded,str) or len(encoded)>28*1024*1024:raise ValueError('Video oltre il limite di 20 MiB.')
        try:data=base64.b64decode(encoded,validate=True)
        except ValueError:raise ValueError('Video codificato non valido.') from None
        if not 0<len(data)<=20*1024*1024:raise ValueError('Video vuoto o oltre 20 MiB.')
        from serve.voicestudio_profiles import _multipart
        fields={'langs':','.join(dict.fromkeys(langs)),'preserve_bg':str(preserve).lower(),'translation_provider':'argos'}
        if voice:fields['voice_id']=voice
        raw_body,content_type=_multipart(fields,(data,'video'+Path(name).suffix.lower()),'video')
        if not client._busy.acquire(blocking=False):raise RuntimeError('Attendi la fine dell’operazione vocale.')
        try:
            client._ready();raw,_,_=client._request('/batch/enqueue',None,raw_body=raw_body,content_type=content_type,timeout=60)
            result=json.loads(raw)
            if not isinstance(result,dict) or not result.get('job_id'):raise RuntimeError('Il runtime non ha confermato la creazione del batch.')
            return {'ok':True,'result':result}
        finally:client._busy.release()
    if kind=='audiobook' and operation=='plan':
        text=payload.get('text');voice=payload.get('default_voice')
        if not isinstance(text,str) or not text.strip() or len(text)>100000:raise ValueError('Inserisci un testo da 1 a 100000 caratteri.')
        if voice is not None and (not isinstance(voice,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',voice)):raise ValueError('Voce predefinita non valida.')
        client._ready();raw,_,_=client._request('/audiobook/plan',{'text':text,'default_voice':voice},timeout=15)
        result=json.loads(raw)
        if not isinstance(result,dict) or not isinstance(result.get('chapters'),list):raise RuntimeError('Piano audiolibro originale non valido.')
        return {'ok':True,'result':result}
    if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',identifier):raise ValueError('Identificativo attività non valido.')
    if kind=='longform' and operation=='download':
        client._ready();raw,_,_=client._request('/longform/jobs?limit=500',timeout=15)
        library=json.loads(raw);rows=library.get('jobs') if isinstance(library,dict) else None
        if not isinstance(rows,list):raise RuntimeError('Libreria audiolibri originale non valida.')
        job=next((row for row in rows if isinstance(row,dict) and row.get('job_id')==identifier),None)
        if job is None:raise ValueError('Audiolibro non presente nella libreria dei risultati completati.')
        name=job.get('output')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_. -]{0,199}\.(?:m4b|mp3)',name):
            raise RuntimeError('Nome del risultato audiolibro non valido.')
        raw,_,mime=client._request('/audio/'+quote(name,safe=''),timeout=60,limit=64*1024*1024)
        container=len(raw)>=12 and raw[4:8]==b'ftyp' if name.endswith('.m4b') else len(raw)>=3 and (raw[:3]==b'ID3' or raw[0]==255 and raw[1]&224==224)
        if not isinstance(mime,str) or mime.split(';')[0] not in ('audio/mp4','audio/x-m4b','audio/mpeg','video/mp4','application/octet-stream') or not container:
            raise RuntimeError('Il runtime non ha restituito un audiolibro valido.')
        return {'ok':True,'file_base64':base64.b64encode(raw).decode('ascii'),'mime':'audio/mp4' if name.endswith('.m4b') else 'audio/mpeg','filename':name}
    if kind=='projects' and operation in ('inspect','rename'):
        if operation=='inspect':
            client._ready();raw,_,_=client._request('/projects/'+identifier,timeout=15,limit=4*1024*1024)
            result=json.loads(raw)
            if not isinstance(result,dict) or result.get('id')!=identifier:raise RuntimeError('Progetto originale non valido.')
            return {'ok':True,'result':result}
        name=payload.get('name')
        if not isinstance(name,str) or not name.strip() or len(name)>200:raise ValueError('Nome progetto: da 1 a 200 caratteri.')
        if not client._busy.acquire(blocking=False):raise RuntimeError('Attendi la fine dell’operazione vocale.')
        try:
            client._ready();raw,_,_=client._request('/projects/'+identifier,{'name':name.strip()},method='PATCH',timeout=15)
            return {'ok':True,'result':json.loads(raw)}
        finally:client._busy.release()
    if kind=='batch' and operation=='download':
        language=payload.get('language')
        if not isinstance(language,str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z]{2,4})?',language):raise ValueError('Lingua del risultato non valida.')
        client._ready();raw,_,mime=client._request('/batch/download/'+identifier+'/'+language,timeout=60,limit=64*1024*1024)
        if mime.split(';')[0]!='video/mp4' or len(raw)<12 or raw[4:8]!=b'ftyp':raise RuntimeError('Il runtime non ha restituito un video MP4 valido.')
        return {'ok':True,'file_base64':base64.b64encode(raw).decode('ascii'),'mime':'video/mp4','filename':identifier+'-'+language+'.mp4'}
    if kind=='batch' and operation in ('cancel','retry'):route='/batch/jobs/'+identifier+'/'+operation
    elif kind=='jobs' and operation=='cancel':route='/tasks/cancel/'+identifier
    else:raise ValueError('Operazione non supportata per questa attività.')
    client._ready();raw,_,_=client._request(route,{},timeout=15)
    return {'ok':True,'result':json.loads(raw)}
