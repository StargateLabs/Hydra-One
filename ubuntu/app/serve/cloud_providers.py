"""Explicit cloud profiles owned by Hydra. No implicit fallback or model startup."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import ipaddress

LOCK = threading.RLock()
LAST_INFERENCE = {}

class ProviderUnavailable(ValueError):
    """Fixed diagnostics only, never an upstream body or credential."""

# Optional second destination ARA may address for spoken turns while "failover"
# stays selected. It is a normal saved profile; only its id is special-cased.
VOICE_PROFILE = 'nvidia-voice'

PRESETS = {
    'nvidia': {'name': 'NVIDIA NIM', 'base_url': 'https://integrate.api.nvidia.com/v1'},
    'openai': {'name': 'OpenAI · Chat Completions', 'base_url': 'https://api.openai.com/v1'},
    'openrouter': {'name': 'OpenRouter', 'base_url': 'https://openrouter.ai/api/v1'},
    'groq': {'name': 'Groq', 'base_url': 'https://api.groq.com/openai/v1'},
    'mistral': {'name': 'Mistral', 'base_url': 'https://api.mistral.ai/v1'},
    'custom': {'name': 'Personalizzato · Chat Completions', 'base_url': ''},
}


def crypt(raw, protect):
    if os.name != 'nt':
        raise ValueError('Il deposito credenziali richiede Windows DPAPI')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source, target = Blob(len(raw), buffer), Blob()
    lib = ctypes.WinDLL('crypt32', use_last_error=True)
    fn = lib.CryptProtectData if protect else lib.CryptUnprotectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Deposito credenziali non accessibile con questo account Windows')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]; free.restype = ctypes.c_void_p
        free(target.data)


def store_path(root):
    return Path(root) / 'data' / 'cloud-providers.dpapi'


def load(root):
    path = store_path(root)
    if not path.exists():
        return {'version': 1, 'selected': 'local', 'profiles': {}}
    if path.stat().st_size > 262144:
        raise ValueError('Deposito provider non valido')
    value = json.loads(crypt(path.read_bytes(), False))
    if value.get('version') != 1 or not isinstance(value.get('profiles'), dict):
        raise ValueError('Formato provider non valido')
    return value


def persist(root, state):
    path = store_path(root); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_bytes(crypt(json.dumps(state, ensure_ascii=False).encode('utf-8'), True))
    os.replace(temp, path)


def public(root):
    with LOCK:
        state = load(root)
    profiles = [{k: v for k, v in row.items() if k != 'api_key'} | {'has_key': bool(row.get('api_key'))}
                for row in state['profiles'].values()]
    return {'selected': state['selected'], 'profiles': profiles, 'presets': PRESETS,
            'protocol': 'chat_completions', 'automatic_fallback': state['selected']=='failover', 'inference':dict(LAST_INFERENCE)}


def validate_url(value):
    if not isinstance(value, str) or len(value) > 500 or any(ord(c) <= 32 for c in value):
        raise ValueError('URL provider non valido')
    parsed = urllib.parse.urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme != 'https'):
        raise ValueError('Usa un URL API senza credenziali, query o frammenti')
    if parsed.hostname == 'localhost' or parsed.hostname.endswith(('.localhost', '.local')):
        raise ValueError('Questa sezione accetta provider cloud; i modelli locali restano gestiti da Hydra')
    try:address = ipaddress.ip_address(parsed.hostname)
    except ValueError:address = None
    if address is not None and not address.is_global:
        raise ValueError('Indirizzo cloud non pubblico')
    return value.rstrip('/')


def save(root, payload):
    fields = {'id', 'name', 'base_url', 'model', 'max_tokens', 'share_memory', 'tools', 'api_key'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('Campi provider non validi')
    identity = payload['id']
    if not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', identity) or identity in ('local', 'pending', 'failover'):
        raise ValueError('Identificatore provider non valido')
    for key, limit in (('name', 80), ('model', 200)):
        if not isinstance(payload[key], str) or (key == 'name' and not payload[key].strip()) or len(payload[key]) > limit or any(ord(c) < 32 for c in payload[key]):
            raise ValueError('Nome o identificatore modello non valido')
    if type(payload['max_tokens']) is not int or not 64 <= payload['max_tokens'] <= 4096:
        raise ValueError('Limite risposta ammesso: 64–4096 token')
    if any(type(payload[key]) is not bool for key in ('share_memory', 'tools')):
        raise ValueError('Opzioni provider non valide')
    secret = payload['api_key']
    if not isinstance(secret, str) or len(secret) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
        raise ValueError('Chiave non valida')
    base = validate_url(payload['base_url'])
    with LOCK:
        state = load(root); previous = state['profiles'].get(identity, {})
        if len(state['profiles']) >= 24 and not previous:
            raise ValueError('Massimo24profili')
        if previous.get('api_key') and not secret and previous.get('base_url') != base:
            raise ValueError('Endpoint cambiato: inserisci una nuova chiave, quella precedente non viene trasferita')
        state['profiles'][identity] = {**payload, 'name': payload['name'].strip(),
            'model': payload['model'].strip(), 'base_url': base, 'api_key': secret or previous.get('api_key', ''),
            'revision': uuid.uuid4().hex}
        if state['selected'] == identity or state['selected']=='failover' and identity in ('nvidia','openrouter'):
            state['selected'] = 'pending'  # Never silently send to a changed destination or fall back locally.
        persist(root, state)
    return public(root)


def select(root, payload):
    if not isinstance(payload, dict) or set(payload) != {'id', 'consent'} or payload['consent'] is not True:
        raise ValueError('Conferma la destinazione delle prossime conversazioni')
    with LOCK:
        state = load(root); identity = payload['id']
        if not isinstance(identity, str) or identity not in ('local','failover') and identity not in state['profiles']:
            raise ValueError('Profilo non disponibile')
        if identity == 'failover':
            for name in ('nvidia','openrouter'):
                row=state['profiles'].get(name,{})
                if not row.get('model') or not row.get('api_key'):raise ValueError('Completa entrambi i profili cloud')
        if identity not in ('local','failover') and not state['profiles'][identity]['model']:
            raise ValueError('Seleziona prima un ID modello')
        if identity not in ('local','failover') and not state['profiles'][identity].get('api_key'):
            raise ValueError('Inserisci e salva la chiave API prima di selezionare il provider')
        state['selected'] = identity; persist(root, state)
    return public(root)


def revoke(root, payload):
    if not isinstance(payload, dict) or set(payload) != {'id', 'confirm'} or payload['confirm'] is not True or not isinstance(payload['id'], str):
        raise ValueError('Conferma la revoca del profilo')
    with LOCK:
        state = load(root)
        if payload['id'] not in state['profiles']: raise ValueError('Profilo non disponibile')
        state['profiles'].pop(payload['id'])
        if state['selected'] == payload['id'] or state['selected']=='failover' and payload['id'] in ('nvidia','openrouter'): state['selected'] = 'pending'
        persist(root, state)
    return public(root)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward a bearer credential to another destination.


def request(profile, suffix, body=None, timeout=60):
    headers = {'Accept': 'audio/wav' if suffix == '/audio/speech' else 'application/json',
               'Content-Type': 'application/json', 'User-Agent': 'ARA/1.0'}
    if profile.get('api_key'):
        headers['Authorization'] = 'Bearer ' + profile['api_key']
    target = validate_url(profile['base_url']) + suffix
    query = urllib.request.Request(target, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(query, timeout=timeout)
    except urllib.error.HTTPError as error:
        code = error.code
        gateway_denied = code == 403 and 'text/html' in error.headers.get('Content-Type', '')
        try:
            value = json.loads(error.read(8193))
            error_code = value.get('error', {}).get('code') if isinstance(value, dict) and isinstance(value.get('error'), dict) else None
        except (ValueError, OSError):
            error_code = None
        finally:
            error.close()
        if gateway_denied:
            raise ProviderUnavailable('Il gateway del provider rifiuta il client Hydra (HTTP 403). Verifica con il provider le condizioni di accesso API; non è una prova di chiave scaduta.') from None
        if error_code == 'model_terms_required':
            raise ProviderUnavailable('Groq richiede l’accettazione dei termini Orpheus nella console Groq. Operazione riservata all’operatore; la chiave non deve essere sostituita.') from None
        detail = {401:'Chiave non valida o scaduta.',403:'Richiesta rifiutata dal provider: controlla autorizzazioni e restrizioni del profilo.',404:'Modello o endpoint non disponibile, anche se compare nel catalogo.',429:'Quota o limite di richieste raggiunto.'}.get(code,'Provider temporaneamente non disponibile.')
        raise ProviderUnavailable('Provider cloud: HTTP ' + str(code) + '. '+detail) from None
    except (urllib.error.URLError, OSError):
        raise ProviderUnavailable('Provider cloud non raggiungibile; nessun fallback automatico') from None


def models(root, payload):
    if not isinstance(payload, dict) or set(payload) != {'id'} or not isinstance(payload['id'], str):
        raise ValueError('Profilo non valido')
    with LOCK:
        row = load(root)['profiles'].get(payload['id'])
    if not row:
        raise ValueError('Salva prima il profilo; puoi usare un ID modello indicato dal provider')
    with request(row, '/models') as response:
        raw = response.read(2097153)
    if len(raw) > 2097152:
        raise ValueError('Catalogo troppo grande')
    values = json.loads(raw).get('data', [])
    return {'models': [v['id'] for v in values if isinstance(v, dict) and isinstance(v.get('id'), str)][:1000],
            'inference_executed': False}


def _forward(handler, root, payload, identity=None):
    if not isinstance(payload, dict) or set(payload) != {'profile', 'revision', 'request'}:
        raise ValueError('Richiesta cloud non valida')
    with LOCK:
        state = load(root)
    if state['selected'] == 'local' or payload['profile'] != state['selected'] and not (
            state['selected']=='failover' and payload['profile'] in ('nvidia','openrouter',VOICE_PROFILE)):
        raise ValueError('La destinazione AI è cambiata: invia nuovamente il messaggio')
    profile = state['profiles'][identity or payload['profile']]; body = payload['request']
    if payload['revision'] != state['profiles'][payload['profile']].get('revision'):
        raise ValueError('Il profilo è cambiato: invia nuovamente il messaggio')
    allowed = {'messages', 'stream', 'tools', 'tool_choice', 'purpose'}
    if not isinstance(body, dict) or set(body) - allowed or not isinstance(body.get('messages'), list):
        raise ValueError('Protocollo Chat Completions non valido')
    if type(body.get('stream', False)) is not bool or len(body['messages']) > 30:
        raise ValueError('Richiesta cloud oltre i limiti')
    if body.get('tools') and not profile['tools']:
        raise ValueError('Tool calling non abilitato per questo profilo')
    purpose=body.get('purpose','conversation')
    if purpose not in ('conversation','greeting') or purpose=='greeting' and (body.get('tools') or body.get('stream')):
        raise ValueError('Tipo turno cloud non valido')
    body={key:value for key,value in body.items() if key!='purpose'}
    # OpenAI reasoning models require max_completion_tokens; compatible providers use max_tokens.
    budget_key = 'max_completion_tokens' if urllib.parse.urlsplit(profile['base_url']).hostname == 'api.openai.com' else 'max_tokens'
    body = {**body, 'model': profile['model'], budget_key: profile['max_tokens']}
    # Documented Bolt voice mode: keep the small response budget for the final answer.
    host = urllib.parse.urlsplit(profile['base_url']).hostname
    if host == 'integrate.api.nvidia.com' and profile['model'] == 'nvidia/nemotron-3.5-bolt-e4b':
        body['chat_template_kwargs'] = {'enable_thinking': False, 'conversational_mode': not bool(body.get('tools'))}
        body['skip_special_tokens'] = False
    elif host == 'integrate.api.nvidia.com' and profile['model'] in (
            'nvidia/nemotron-3.5-super-vl-120b-a12b', 'nvidia/nemotron-3.5-lightning-30b-a3b'):
        body['chat_template_kwargs'] = {'enable_thinking': False}
        body['temperature'] = 0.2
    if purpose=='greeting':
        body[budget_key]=min(profile['max_tokens'],96)
        body['temperature']=0.85
        body['top_p']=0.95
    import time
    with LOCK:LAST_INFERENCE.update(provider=identity or payload['profile'],model=profile['model'],phase='connecting',started_at=time.time())
    with request(profile, '/chat/completions', body, timeout=15 if state['selected']=='failover' else 60) as response:
        if not body.get('stream'):
            raw = response.read(2097153)
            if len(raw) > 2097152:
                raise ValueError('Risposta cloud oltre il limite')
            value=json.loads(raw)
            if not value.get('choices') or not (value['choices'][0].get('message',{}).get('content') or value['choices'][0].get('message',{}).get('tool_calls')):raise ProviderUnavailable('Risposta cloud vuota')
            handler._cloud_started=True
            handler._json(200, value); return
        if 'text/event-stream' not in response.headers.get('Content-Type', ''):
            raise ValueError('Il provider non ha restituito uno stream SSE')
        # Hold headers until actual text arrives: an empty/failed stream can use the reserve.
        import time
        deadline=time.monotonic()+20
        buffered=[]; size=0
        while True:
            if time.monotonic()>deadline:raise ProviderUnavailable('Tempo massimo primo testo cloud superato')
            line=response.readline(65537);size+=len(line)
            if not line or size>262144:raise ProviderUnavailable('Stream cloud senza testo')
            buffered.append(line)
            if line.startswith(b'data:'):
                raw=line[5:].strip()
                if raw==b'[DONE]':raise ProviderUnavailable('Risposta cloud vuota')
                try:value=json.loads(raw)
                except ValueError:raise ProviderUnavailable('Stream cloud non valido') from None
                if value.get('error'):raise ProviderUnavailable('Stream cloud non disponibile')
                choices=value.get('choices',[])
                if choices and (choices[0].get('delta',{}).get('content') or choices[0].get('delta',{}).get('tool_calls')):break
        handler._cloud_started=True
        with LOCK:LAST_INFERENCE['phase']='responding'
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Connection', 'close'); handler.end_headers()
        handler.close_connection = True
        for line in buffered:handler.wfile.write(line)
        handler.wfile.flush()
        import time
        started = time.monotonic(); total = 0
        try:
            while True:
                line = response.readline(262145)
                if not line: break
                total += len(line)
                if len(line) > 262144 or total > 4194304 or time.monotonic() - started > 180:
                    break  # Missing DONE makes the caller reject an incomplete answer.
                handler.wfile.write(line); handler.wfile.flush()
                if line.strip() == b'data: [DONE]':
                    handler.wfile.write(b'\n'); handler.wfile.flush(); break
        except (OSError, TimeoutError):
            pass  # Close upstream on cancellation; never append JSON to SSE.



def _dispatch(handler, root, payload):
    with LOCK:state=load(root)
    if state['selected']!='failover':return _forward(handler,root,payload)
    # ARA speaks through an optional fast profile while the primary keeps answering
    # everything else. This route never falls back: a voice turn either answers here
    # or fails visibly, so the operator never hears the reserve model unexpectedly.
    if isinstance(payload,dict) and payload.get('profile')==VOICE_PROFILE:
        return _forward(handler,root,payload)
    if not isinstance(payload,dict) or payload.get('profile')!='nvidia':raise ValueError('Profilo primario non valido')
    handler._cloud_started=False
    try:return _forward(handler,root,payload,'nvidia')
    except (ProviderUnavailable,OSError,ValueError):
        if handler._cloud_started:raise
    # Only transport/model generation is retried. No tools have been executed here.
    return _forward(handler,root,payload,'openrouter')


def forward(handler, root, payload):
    try:return _dispatch(handler,root,payload)
    finally:
        import time
        with LOCK:
            if LAST_INFERENCE:LAST_INFERENCE.update(phase='idle',finished_at=time.time())


def duplicate(root, payload):
    """Copy a saved profile under a new id, keeping its credential inside Hydra.

    ARA creates the optional fast voice profile this way: the key never leaves the
    DPAPI store, and the operator can still edit or revoke both profiles normally.
    """
    if not isinstance(payload, dict) or set(payload) != {'from', 'id', 'model', 'max_tokens', 'tools'}:
        raise ValueError('Duplicazione profilo non valida')
    source, identity = payload['from'], payload['id']
    if not isinstance(source, str) or not isinstance(identity, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', identity):
        raise ValueError('Identificatore non valido')
    if identity in ('local', 'pending', 'failover') or identity == source:
        raise ValueError('Identificatore riservato')
    if not isinstance(payload['model'], str) or not payload['model'].strip() or len(payload['model']) > 200:
        raise ValueError('Modello non valido')
    if type(payload['max_tokens']) is not int or not 64 <= payload['max_tokens'] <= 4096:
        raise ValueError('Limite risposta ammesso: 64-4096 token')
    if type(payload['tools']) is not bool:
        raise ValueError('Opzione strumenti non valida')
    with LOCK:
        state = load(root)
        origin = state['profiles'].get(source)
        if not origin or not origin.get('api_key'):
            raise ValueError('Il profilo da copiare non ha una chiave salvata')
        if len(state['profiles']) >= 24 and identity not in state['profiles']:
            raise ValueError('Massimo 24 profili')
        state['profiles'][identity] = {**origin, 'id': identity, 'model': payload['model'].strip(),
                                       'max_tokens': payload['max_tokens'], 'tools': payload['tools'],
                                       'revision': uuid.uuid4().hex}
        persist(root, state)
    return public(root)


def route(handler, svc, path, post=False):
    paths = {'/cloud/providers', '/cloud/providers/save', '/cloud/providers/select', '/cloud/providers/models', '/cloud/providers/revoke', '/cloud/providers/duplicate', '/cloud/chat'}
    if path not in paths:
        return False
    if not handler._authorized() or not handler._own_page('Provider cloud gestiti soltanto dalla dashboard locale'):
        return True
    root = svc.update_center.root
    try:
        if not post:
            if path != '/cloud/providers': raise ValueError('Metodo non ammesso')
            handler._json(200, public(root)); return True
        limit = 131072 if path == '/cloud/chat' else 8192
        if not 0 < int(handler.headers.get('Content-Length', 0)) <= limit:
            raise ValueError('Richiesta oltre il limite')
        payload = json.loads(handler._read_body())
        if path == '/cloud/chat':
            forward(handler, root, payload); return True
        operation = {'/cloud/providers/save': save, '/cloud/providers/select': select, '/cloud/providers/models': models,
                     '/cloud/providers/revoke': revoke, '/cloud/providers/duplicate': duplicate}.get(path)
        if operation is None: raise ValueError('Metodo non ammesso')
        handler._json(200, operation(root, payload))
    except ProviderUnavailable as error:
        handler._json(502, {'error': {'message': str(error)}})
    except (ValueError, OSError, TypeError, KeyError):
        # No upstream body, credentials or arbitrary URL in diagnostics.
        handler._json(400, {'error': {'message': 'Operazione cloud non riuscita. Controlla profilo, endpoint, modello, chiave e quota; nessun fallback eseguito.'}})
    return True
