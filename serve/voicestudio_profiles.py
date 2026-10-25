"""Bounded original profile contracts. No destructive profile deletion or DB copies."""
import base64
import ast
import json
import re
import uuid
from pathlib import Path

LIMIT=20*1024*1024

def design_catalog(desktop):
    if desktop is None:return []
    def literal(path,name):
        if path.stat().st_size>1024*1024:raise ValueError('Design metadata exceeds bound')
        tree=ast.parse(path.read_text(encoding='utf-8-sig'))
        node=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id==name for target in node.targets))
        return ast.literal_eval(node.value)
    try:
        resources=desktop.parent/'resources'
        order=literal(resources/'backend/core/describe_voice.py','CATEGORY_ORDER')
        groups=literal(resources/'omnivoice/utils/voice_design.py','_INSTRUCT_CATEGORIES')
        names=literal(resources/'backend/core/describe_voice.py','DIALECT_PINYIN')
        if not isinstance(order,(tuple,list)) or not isinstance(groups,list) or len(order)!=len(groups):return []
        aliases={value:key.title() for key,value in names.items()} if isinstance(names,dict) else {}
        return [{'category':category,'options':[{'value':value,'label':aliases.get(value,value)} for value in sorted(group)]} for category,group in zip(order,groups) if isinstance(category,str) and isinstance(group,(dict,set,list,tuple))]
    except (OSError,ValueError,SyntaxError,StopIteration,TypeError):return []

def _file(payload,bundle=False):
    encoded=payload.get('file_base64')
    if not isinstance(encoded,str) or not encoded or len(encoded)>((LIMIT+2)//3)*4:
        raise ValueError('File vocale mancante o oltre 20 MiB.')
    try:data=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError) as error:raise ValueError('File vocale non valido.') from error
    if not data or len(data)>LIMIT:raise ValueError('File vocale mancante o oltre 20 MiB.')
    if bundle:
        if not data.startswith(b'PK'):raise ValueError('Seleziona un pacchetto vocale .ovsvoice originale.')
        return data,'voice.ovsvoice'
    suffix=Path(str(payload.get('file_name','reference.wav'))).suffix.lower()
    if suffix not in ('.wav','.mp3','.flac','.ogg','.m4a','.aac','.webm'):
        raise ValueError('Formato audio di riferimento non supportato.')
    return data,'reference'+suffix

def _multipart(fields,file=None,file_field='ref_audio'):
    boundary='strata-'+uuid.uuid4().hex
    parts=[]
    for name,value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8'))
    if file:
        data,filename=file
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()+data+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts),'multipart/form-data; boundary='+boundary

def _fields(payload):
    result={}
    for name,limit in [('name',200),('ref_text',4096),('instruct',4096),('language',64),('personality',100)]:
        if name not in payload:continue
        value=payload[name]
        if not isinstance(value,str) or len(value)>limit:raise ValueError('Campo del profilo non valido: '+name)
        if name=='name' and not value.strip():raise ValueError('Inserisci il nome della voce.')
        result[name]=value
    return result

def profile_action(client,payload):
    if not isinstance(payload,dict):raise ValueError('Profilo vocale non valido.')
    action=payload.get('action');identifier=payload.get('id','')
    route=None;body=None;raw_body=None;content_type=None;method='POST';binary=False
    if action=='describe':
        description=payload.get('description')
        if not isinstance(description,str) or not description.strip() or len(description)>2000:raise ValueError('Descrizione vocale: da 1 a 2000 caratteri.')
        route='/design/describe';body={'description':description}
    elif action in ('update','export'):
        if not isinstance(identifier,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',identifier):raise ValueError('Profilo vocale non valido.')
        if action=='update':
            body=_fields(payload)
            if not body:raise ValueError('Nessuna modifica del profilo.')
            route='/profiles/'+identifier;method='PUT'
        else:route='/personas/export/'+identifier;binary=True
    elif action in ('import','inspect'):
        raw_body,content_type=_multipart({},_file(payload,bundle=True),'file')
        route='/personas/'+action
    elif action in ('create_clone','create_design'):
        fields=_fields(payload)
        if 'name' not in fields:raise ValueError('Inserisci il nome della voce.')
        fields['kind']='clone' if action=='create_clone' else 'design'
        if action=='create_clone':file=_file(payload)
        else:
            file=None;states=payload.get('vd_states',{})
            if not isinstance(states,dict) or len(states)>30 or any(not isinstance(key,str) or not isinstance(value,str) or len(key)>50 or len(value)>200 for key,value in states.items()):raise ValueError('Configurazione della voce non valida.')
            fields['vd_states']=json.dumps(states)
        raw_body,content_type=_multipart(fields,file);route='/profiles'
    else:raise ValueError('Operazione del profilo non supportata.')
    if not client._busy.acquire(blocking=False):raise RuntimeError('Attendi la fine della generazione vocale.')
    try:
        client._ready()
        kwargs={'timeout':300,'method':method,'limit':LIMIT if binary else 1024*1024}
        if raw_body is not None:kwargs.update(raw_body=raw_body,content_type=content_type)
        raw,_,mime=client._request(route,body,**kwargs)
        if binary:
            if not raw.startswith(b'PK'):raise RuntimeError('VoiceStudio non ha restituito un pacchetto vocale valido.')
            return {'ok':True,'file_base64':base64.b64encode(raw).decode('ascii'),'filename':identifier+'.ovsvoice','mime':'application/octet-stream'}
        return {'ok':True,'result':json.loads(raw)}
    finally:client._busy.release()
