"""Opt-in message-based connector. Independent of Strata's token/engine protocol.

No upstream Studio code is copied, no packages are installed, and no model is
loaded by this module. Availability is established by an actual local API probe.
"""
import http.client
import ipaddress
import json
import socket
import threading
from urllib.parse import urlsplit


class BackendError(RuntimeError):
    pass


class LocalOpenAIBackend:
    def __init__(self, base_url, api_key=None, timeout=10):
        parsed = urlsplit(base_url)
        host = parsed.hostname
        if host == 'localhost':
            host = '127.0.0.1'
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = False
        if (parsed.scheme != 'http' or not local or parsed.username or
                parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Il backend deve essere un endpoint HTTP locale senza credenziali nell’URL')
        if not parsed.path.rstrip('/').endswith('/v1'):
            raise ValueError('Usa il percorso API versionato /v1 del backend')
        self.host, self.port = host, parsed.port or 80
        self.path = parsed.path.rstrip('/')
        self.api_key, self.timeout = api_key, timeout

    def _request(self, method, suffix, body=None, *, cancel=None):
        from serve.hydra_http_pool import local_endpoint
        local_endpoint(self.host,self.port,self.timeout)
        if cancel is not None and cancel.is_set():raise BackendError('Richiesta annullata')
        connection = getattr(self, 'connection_factory', http.client.HTTPConnection)(self.host, self.port, timeout=self.timeout)
        headers = {'Accept': 'application/json'}
        if self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        payload = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        waiting=threading.Event()
        try:
            if method=='POST':
                connection.connect()
                if cancel is not None and cancel.is_set():raise BackendError('Richiesta annullata')
                connection.sock.settimeout(self.timeout)
                if cancel is not None:
                    active_socket=connection.sock
                    def cancel_headers():
                        while not waiting.wait(.05):
                            if cancel.is_set():
                                try:active_socket.shutdown(socket.SHUT_RDWR)
                                except OSError:pass
                                return
                    threading.Thread(target=cancel_headers,daemon=True).start()
            connection.request(method, self.path + suffix, body=payload, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                detail=''
                try:
                    error=json.loads(response.read(16384)).get('error')
                    detail=error.get('message','') if isinstance(error,dict) else str(error or '')
                except (ValueError,OSError):pass
                raise BackendError(f'Backend HTTP {response.status}: {detail[:800] or "nessun risultato utilizzabile"}')
            return connection, response
        except BaseException:
            connection.close()
            raise
        finally:
            waiting.set()

    @staticmethod
    def _json_response(response):
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise BackendError('Risposta del backend troppo grande')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('error'):
            raise BackendError('Risposta del backend non valida')
        # Chunked JSON has length=None even after complete consumption. This
        # marker is read only by the opt-in laboratory connection pool; SSE and
        # interrupted/oversized/invalid responses never receive it.
        response._hydra_body_consumed = True
        return result

    def models(self):
        connection, response = self._request('GET', '/models')
        try:
            result = self._json_response(response)
            rows = result.get('data')
            if not isinstance(rows, list) or any(not isinstance(r, dict) or
                    not isinstance(r.get('id'), str) for r in rows):
                raise BackendError('Elenco dei modelli non valido')
            return rows
        finally:
            connection.close()

    @staticmethod
    def model_metadata(row):
        """Keep a declared model limit distinct from an active runtime context."""
        declared=None
        for key in ('max_model_len','context_length','max_position_embeddings'):
            value=row.get(key)
            if type(value) is int and 1024<=value<=4194304:
                declared=value;break
        active=row.get('active_context_length')
        if type(active) is not int or not 1024<=active<=4194304:active=None
        inputs=row.get('input_modalities')
        inputs=inputs if isinstance(inputs,list) else ['text']
        return dict(model_max_context=declared,active_context=active,
                    context_source='api_model_metadata' if active is not None else 'not_reported',
                    input_modalities=[name for name in ('text','image','audio','video') if name in inputs],
                    publisher=row.get('owned_by') if isinstance(row.get('owned_by'),str) else None)

    def chat(self, messages, model, max_tokens=128, *, stream=False, cancel=None, **options):
        if not isinstance(model, str) or not model:
            raise ValueError('Seleziona il modello del backend, senza sostituirlo automaticamente')
        if not isinstance(messages, list) or not messages:
            raise ValueError('Messaggi mancanti')
        if type(max_tokens) is not int or not 1 <= max_tokens <= getattr(self,'max_output_tokens',4096):
            raise ValueError('Budget di generazione non valido')
        if any(not isinstance(m, dict) or m.get('role') not in
               ('system', 'developer', 'user', 'assistant', 'tool') for m in messages):
            raise ValueError('Ruolo dei messaggi non valido')
        allowed = {'temperature', 'top_p', 'top_k', 'seed', 'stop', 'tools', 'tool_choice',
                   'parallel_tool_calls', 'response_format','chat_template_kwargs','reasoning_effort','cache_prompt','timings_per_token','cache_slot','enable_thinking','ignore_eos'}
        if options.keys() - allowed:
            raise ValueError('Opzioni del backend non riconosciute')
        if 'cache_slot' in options and (type(options['cache_slot']) is not int or not 0<=options['cache_slot']<1024):
            raise ValueError('Sessione KV non valida')
        if 'enable_thinking' in options and type(options['enable_thinking']) is not bool:
            raise ValueError('Impostazione ragionamento non valida')
        if 'ignore_eos' in options and type(options['ignore_eos']) is not bool:
            raise ValueError('ignore_eos boolean required')
        # Templates commonly accept one system message, strictly at index zero.
        instructions=[m.get('content') for m in messages if m.get('role') in ('system','developer')]
        if any(not isinstance(content,str) for content in instructions):raise ValueError('System instructions must be text')
        messages=([dict(role='system',content='\n\n'.join(instructions))] if instructions else [])+[m for m in messages if m.get('role') not in ('system','developer')]
        body = dict(messages=messages, model=model, max_tokens=max_tokens, stream=stream, **options)
        if stream:
            body['stream_options'] = {'include_usage': True}
        if cancel is not None and cancel.is_set():
            return
        try:connection, response = self._request('POST', '/chat/completions', body,cancel=cancel)
        except (OSError,BackendError):
            if cancel is not None and cancel.is_set():return
            raise
        finished = threading.Event()
        # Closing an HTTP response alone can wait for its blocked read lock.
        # Shutdown the underlying socket first so Stop interrupts stalled SSE.
        active_socket = connection.sock or getattr(getattr(response, 'fp', None), 'raw', None)
        active_socket = getattr(active_socket, '_sock', active_socket)
        def watch_cancel():
            while not finished.wait(.05):
                if cancel.is_set():
                    try: active_socket.shutdown(socket.SHUT_RDWR)
                    except (OSError, AttributeError): pass
                    return
        if cancel is not None:
            threading.Thread(target=watch_cancel, daemon=True).start()
        try:
            if not stream:
                result = self._json_response(response)
                if not isinstance(result.get('choices'), list) or not result['choices']:
                    raise BackendError('Completamento privo di risposta')
                if cancel is None or not cancel.is_set():yield result
                return
            content_type = response.getheader('Content-Type', '').split(';')[0].strip()
            if content_type != 'text/event-stream':
                raise BackendError('Il backend non ha restituito uno stream SSE')
            data = []
            size = 0
            while cancel is None or not cancel.is_set():
                line = response.readline(1024 * 1024 + 1)
                if len(line) > 1024 * 1024:
                    raise BackendError('Evento stream troppo grande')
                if not line:
                    if cancel is not None and cancel.is_set():return
                    raise BackendError('Stream interrotto prima del completamento')
                line = line.decode('utf-8').rstrip('\r\n')
                if line.startswith('data:'):
                    value = line[5:].lstrip()
                    size += len(value)
                    if size > 1024 * 1024:
                        raise BackendError('Evento stream troppo grande')
                    data.append(value)
                elif not line and data:
                    payload = '\n'.join(data)
                    data, size = [], 0
                    if payload == '[DONE]':
                        return
                    result = json.loads(payload)
                    if not isinstance(result, dict) or result.get('error'):
                        raise BackendError('Errore di generazione dal backend')
                    if not isinstance(result.get('choices'), list):
                        raise BackendError('Evento stream non conforme')
                    yield result
        except (OSError, ValueError):
            if cancel is None or not cancel.is_set():raise
        finally:
            finished.set()
            response.close()
            connection.close()
