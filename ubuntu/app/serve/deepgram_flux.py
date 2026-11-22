"""Hydra route for operator-selected Deepgram Flux turns; DPAPI owns the key."""
import asyncio
import base64
import io
import json
import wave
from pathlib import Path

DEFAULT = {
    'profile': {'model': 'flux-general-multi', 'language_hint': 'it', 'eot_threshold': .7,
                'eot_timeout_ms': 1500, 'keyterms': ['Ara']},
    'api_key': '', 'consent': False, 'enabled': False,
}


def _path(root):
    return Path(root) / 'data' / 'deepgram-flux.dpapi'


def _load(root):
    path = _path(root)
    if not path.exists():
        return dict(DEFAULT)
    if path.stat().st_size > 16384:
        raise ValueError('Profilo Deepgram non valido')
    from serve.cloud_providers import crypt
    value = json.loads(crypt(path.read_bytes(), False))
    if (not isinstance(value, dict) or set(value) != set(DEFAULT)
            or not isinstance(value.get('profile'), dict)
            or not isinstance(value.get('api_key'), str)
            or type(value.get('consent')) is not bool
            or type(value.get('enabled')) is not bool):
        raise ValueError('Profilo Deepgram non valido')
    return value


def _validate_profile(value):
    expected = {'model', 'language_hint', 'eot_threshold', 'eot_timeout_ms', 'keyterms'}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('Campi Flux non validi')
    if value['model'] != 'flux-general-multi' or value['language_hint'] not in ('it', 'en'):
        raise ValueError('Modello o lingua Flux non validi')
    if type(value['eot_threshold']) not in (int, float) or not .5 <= value['eot_threshold'] <= 1:
        raise ValueError('Soglia fine turno ammessa: 0,5–1')
    if type(value['eot_timeout_ms']) is not int or not 500 <= value['eot_timeout_ms'] <= 60000:
        raise ValueError('Pausa massima ammessa: 500–60000 ms')
    terms = value['keyterms']
    if (not isinstance(terms, list) or not 1 <= len(terms) <= 10
            or any(not isinstance(term, str) or not 1 <= len(term) <= 40
                   or any(ord(char) < 32 for char in term) for term in terms)):
        raise ValueError('Da 1 a 10 termini, massimo 40 caratteri ciascuno')
    return dict(value)


def status(root):
    value = _load(root)
    try:
        from websockets.asyncio.client import connect as _connect
        available = True
    except ImportError:
        available = False
    return {'profile': value['profile'], 'enabled': value['enabled'], 'consent': value['consent'],
            'has_key': bool(value['api_key']), 'runtime_available': available,
            'active': value['enabled'] and value['consent'] and bool(value['api_key']) and available,
            'endpoint': 'wss://api.deepgram.com/v2/listen', 'encoding': 'linear16',
            'sample_rate': 16000, 'chunk_ms': 80}


def save(root, payload):
    fields = {'profile', 'api_key', 'consent', 'enabled'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError('Campi Deepgram non validi')
    profile = _validate_profile(payload['profile'])
    key = payload['api_key']
    if not isinstance(key, str) or len(key) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise ValueError('Chiave Deepgram non valida')
    if type(payload['consent']) is not bool or type(payload['enabled']) is not bool:
        raise ValueError('Consenso o selezione Deepgram non validi')
    previous = _load(root)
    key = key.strip() or previous['api_key']
    if payload['enabled'] and (payload['consent'] is not True or not key):
        raise ValueError('Selezione Deepgram richiede chiave e consenso esplicito')
    if payload['enabled']:
        try:
            import websockets.asyncio.client  # noqa: F401
        except ImportError:
            raise ValueError('Dipendenza WebSocket Hydra non installata') from None
    value = {'profile': profile, 'api_key': key, 'consent': payload['consent'], 'enabled': payload['enabled']}
    from serve.cloud_providers import crypt
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(crypt(json.dumps(value, ensure_ascii=False).encode('utf-8'), True))
    temporary.replace(path)
    return status(root)


async def transcribe(root, payload):
    state = _load(root)
    if not state['enabled'] or not state['consent'] or not state['api_key']:
        raise ValueError('Invio audio a Deepgram non autorizzato')
    if not isinstance(payload, dict) or set(payload) != {'audio_base64'} or not isinstance(payload['audio_base64'], str) or len(payload['audio_base64']) > 1400000:
        raise ValueError('Audio Deepgram oltre il limite')
    raw = base64.b64decode(payload['audio_base64'], validate=True)
    with wave.open(io.BytesIO(raw), 'rb') as wav:
        frames = wav.getnframes()
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000) or not 160 <= frames <= 320000:
            raise ValueError('Richiesto WAV mono PCM16 16 kHz fino a 20 secondi')
        pcm = wav.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError('Audio Deepgram incompleto')
    from serve.deepgram_flux_transport import transcribe_turn
    text = await transcribe_turn(raw, state['profile'], api_key=state['api_key'], audio_consent=state['consent'])
    return {'text': text, 'model': state['profile']['model'], 'diagnostic': 'accepted' if text else 'no_words'}


def route(handler, svc, path, post=False):
    routes = {'/cloud/deepgram', '/cloud/deepgram/save', '/cloud/deepgram/audio'}
    if path not in routes:
        return False
    if not handler._authorized() or not handler._own_page('Configurazione e invio audio Deepgram dalla dashboard locale'):
        return True
    from serve.cloud_providers import ProviderUnavailable
    root = svc.update_center.root
    try:
        if not post and path == '/cloud/deepgram':
            handler._json(200, status(root))
            return True
        if not post or path not in routes - {'/cloud/deepgram'}:
            raise ValueError('Metodo non ammesso')
        limit = 1401000 if path.endswith('/audio') else 16384
        if not 0 < int(handler.headers.get('Content-Length', 0)) <= limit:
            raise ValueError('Richiesta oltre il limite')
        payload = json.loads(handler._read_body())
        if path.endswith('/save'):
            handler._json(200, save(root, payload))
        else:
            result = asyncio.run(transcribe(root, payload))
            handler._json(200, result)
    except ProviderUnavailable as error:
        handler._json(502, {'error': {'message': str(error)}})
    except (ValueError, OSError, TypeError, KeyError, wave.Error):
        handler._json(400, {'error': {'message': 'Deepgram non disponibile: verifica stato, consenso, credenziale e formato audio.'}})
    return True
