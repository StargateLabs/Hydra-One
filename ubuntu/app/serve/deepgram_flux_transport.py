"""Bounded Flux transport for an already captured turn; Hydra owns consent and credentials."""
import asyncio
import io
import json
import wave

from serve.deepgram_flux_protocol import parse_frame, websocket_url


async def transcribe_turn(wav_bytes, profile, *, api_key, audio_consent, connect=None):
    if audio_consent is not True:
        raise ValueError('Consenso audio Deepgram richiesto')
    if not isinstance(api_key, str) or not 1 <= len(api_key) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
        raise ValueError('Credenziale Deepgram non valida')
    if not isinstance(wav_bytes, bytes) or len(wav_bytes) > 1000000:
        raise ValueError('Audio Deepgram oltre il limite')
    try:
        with wave.open(io.BytesIO(wav_bytes), 'rb') as audio:
            frames = audio.getnframes()
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000) or not 160 <= frames <= 320000:
                raise ValueError('Richiesto WAV mono PCM16 16 kHz fino a 20 secondi')
            pcm = audio.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError('Audio Deepgram incompleto')
    except (wave.Error, EOFError) as from_error:
        raise ValueError('Formato audio Deepgram non valido') from from_error
    url = websocket_url(profile)
    if connect is None:
        from websockets.asyncio.client import connect
    async def run():
        async with connect(url, additional_headers={'Authorization': 'Token ' + api_key}, open_timeout=5, close_timeout=2, max_size=65536, proxy=None) as connection:
            async def send():
                for start in range(0, len(pcm), 2560):
                    await connection.send(pcm[start:start + 2560])
                    await asyncio.sleep(.08)
                await connection.send(json.dumps({'type': 'ForceEndTurn'}))
            sender = asyncio.create_task(send())
            try:
                async for frame in connection:
                    text = parse_frame(frame)
                    if text is not None:
                        await sender
                        return text
                raise ValueError('Flusso Deepgram terminato senza trascrizione finale')
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
    try:
        return await asyncio.wait_for(run(), timeout=30)
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ValueError('Trascrizione Deepgram non riuscita: verifica connessione, consenso, chiave e credito') from None

