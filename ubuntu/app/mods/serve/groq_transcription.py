"""Hydra module: explicit, revocable microphone upload using its protected Groq key."""
import base64
import io
import json
from pathlib import Path
import urllib.error
import urllib.request
import uuid
import wave
import math

MODELS = ('whisper-large-v3-turbo', 'whisper-large-v3')
DEFAULT = {'enabled': False, 'model': MODELS[0], 'language': 'it'}

def recognized_text(result):
    text=result.get('text')
    if not isinstance(text,str) or len(text)>8000:raise ValueError('Risposta trascrizione non valida')
    segments=result.get('segments')
    if not isinstance(segments,list):raise ValueError('Metadati affidabilità trascrizione mancanti')
    accepted=[]
    for segment in segments:
        if not isinstance(segment,dict):raise ValueError('Segmento trascrizione non valido')
        metrics=[segment.get(key) for key in ('no_speech_prob','avg_logprob','compression_ratio')]
        if any(type(value) not in (int,float) or not math.isfinite(value) for value in metrics):raise ValueError('Confidenza trascrizione non valida')
        no_speech,logprob,compression=metrics
        # Whisper silence is joint no-speech/logprob evidence; proper names can score low.
        if (no_speech>=.6 and logprob<=-1.0) or logprob< -2.0 or compression>2.4:continue
        fragment=segment.get('text')
        if not isinstance(fragment,str):raise ValueError('Testo segmento non valido')
        accepted.append(fragment.strip())
    return ' '.join(accepted).strip()


def status(root):
    path = Path(root) / 'data/groq-transcription.json'
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(DEFAULT)
    from serve.groq_voice import load
    return {**state, 'has_key': bool(load(root).get('api_key')), 'available': True}


def save(root, payload):
    if not isinstance(payload, dict) or set(payload) != set(DEFAULT):
        raise ValueError('Campi trascrizione non validi')
    if type(payload['enabled']) is not bool or payload['model'] not in MODELS or payload['language'] not in ('it', 'en', 'auto'):
        raise ValueError('Selezione trascrizione non valida')
    if payload['enabled'] and not status(root)['has_key']:
        raise ValueError('Salva prima la chiave Groq nel deposito protetto Hydra')
    from serve.configuration import atomic_json
    atomic_json(Path(root) / 'data/groq-transcription.json', payload)
    return status(root)


def audio(root, payload):
    state = status(root)
    if state.get('enabled') is not True or not state.get('has_key'):
        raise ValueError('Invio audio del microfono a Groq non autorizzato')
    if not isinstance(payload, dict) or set(payload) != {'audio_base64'} or not isinstance(payload['audio_base64'], str) or len(payload['audio_base64']) > 1400000:
        raise ValueError('Audio oltre il limite')
    raw = base64.b64decode(payload['audio_base64'], validate=True)
    with wave.open(io.BytesIO(raw), 'rb') as wav:
        n = wav.getnframes()
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000 or not 160 <= n <= 16000 * 30:
            raise ValueError('Richiesto WAV mono PCM16 a 16 kHz, fino a 30 secondi')
        if len(wav.readframes(n)) != n * 2:
            raise ValueError('Audio incompleto')
    boundary = 'HydraGroq' + uuid.uuid4().hex
    fields = {'model': state['model'], 'temperature': '0', 'response_format': 'verbose_json'}
    if state['language']=='it':fields['prompt']='Conversazione in italiano. Il nome proprio dell’assistente è Ara.'
    if state['language'] != 'auto':
        fields['language'] = state['language']
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()]
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="turn.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + raw + b'\r\n', f'--{boundary}--\r\n'.encode()]
    from serve.groq_voice import load
    from serve.cloud_providers import NoRedirect, ProviderUnavailable
    query = urllib.request.Request('https://api.groq.com/openai/v1/audio/transcriptions', data=b''.join(parts), headers={
        'Authorization': 'Bearer ' + load(root)['api_key'], 'User-Agent': 'Hydra-One/1.0 ARA/1.0',
        'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Accept': 'application/json'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(query, timeout=15) as response:
            result = response.read(65537)
        if len(result) > 65536:
            raise ValueError('Trascrizione oltre il limite')
        decoded=json.loads(result)
        text = recognized_text(decoded)
        return {'text': text.strip(), 'model': state['model'], 'diagnostic': 'accepted' if text else 'confidence_rejected' if decoded.get('text','').strip() else 'no_words'}
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ProviderUnavailable('Trascrizione Groq rifiutata (HTTP ' + str(code) + '): verifica chiave, quota e accesso al modello.') from None
    except (urllib.error.URLError, OSError):
        raise ProviderUnavailable('Trascrizione Groq non raggiungibile; nessun fallback automatico.') from None


def route(handler, svc, path, post=False):
    if path not in ('/cloud/transcription', '/cloud/transcription/save', '/cloud/transcription/audio'):
        return False
    if not handler._authorized() or not handler._own_page('Consenso audio Groq dalla dashboard locale'):
        return True
    from serve.cloud_providers import ProviderUnavailable
    try:
        root = svc.update_center.root
        if not post and path == '/cloud/transcription':
            handler._json(200, status(root))
        elif post and path.endswith(('/save', '/audio')):
            limit = 1401000 if path.endswith('/audio') else 1024
            if not 0 < int(handler.headers.get('Content-Length', 0)) <= limit:
                raise ValueError('Richiesta oltre il limite')
            payload = json.loads(handler._read_body())
            handler._json(200, audio(root, payload) if path.endswith('/audio') else save(root, payload))
        else:
            raise ValueError('Metodo non valido')
    except ProviderUnavailable as exc:
        handler._json(502, {'error': {'message': str(exc)}})
    except (ValueError, OSError, KeyError, TypeError, wave.Error):
        handler._json(400, {'error': {'message': 'Trascrizione non disponibile: verifica consenso audio, chiave e formato.'}})
    return True
