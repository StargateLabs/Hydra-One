"""Flux protocol helpers; no credentials, sockets, audio capture, or provider selection."""
import json
from urllib.parse import urlencode

from serve.deepgram_flux import _validate_profile as validate


def websocket_url(profile):
    settings = validate(profile)
    query = [('model', settings['model']), ('encoding', 'linear16'), ('sample_rate', '16000'),
             ('language_hint', settings['language_hint']), ('eot_threshold', str(settings['eot_threshold'])),
             ('eot_timeout_ms', str(settings['eot_timeout_ms']))]
    query.extend(('keyterm', term) for term in settings['keyterms'])
    return 'wss://api.deepgram.com/v2/listen?' + urlencode(query)


def final_transcript(message):
    if not isinstance(message, dict):
        raise ValueError('Messaggio Flux non valido')
    if message.get('type') == 'Error':
        raise ValueError('Il servizio Flux ha restituito un errore')
    if message.get('type') != 'TurnInfo' or message.get('event') != 'EndOfTurn':
        return None
    transcript = message.get('transcript')
    if not isinstance(transcript, str) or len(transcript) > 8000:
        raise ValueError('Trascrizione Flux non valida')
    return transcript.strip()


def parse_frame(raw):
    if not isinstance(raw, str) or len(raw) > 65536:
        raise ValueError('Messaggio Flux oltre il limite')
    try:
        return final_transcript(json.loads(raw))
    except (ValueError, TypeError) as error:
        raise ValueError('Risposta Flux non valida') from error
