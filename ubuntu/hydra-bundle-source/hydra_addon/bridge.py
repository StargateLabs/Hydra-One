"""Single-listener loopback bridge; never imports any protected gateway."""
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import select
import socket
import threading
import time
from hydra_lab.adapters import Pending


def validate_bind(host):
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError('Only literal loopback addresses are allowed')
    return host


def forward(adapter, body, write, *, on_headers=None, pending=None):
    pending = pending or Pending()
    connection = response = None
    primary = None
    try:
        connection, response = adapter.open('POST', '/v1/chat/completions', body, pending)
        kind = response.getheader('Content-Type', 'application/json')
        if on_headers:
            on_headers(response.status, kind)
        read = getattr(response, 'read1', response.read)
        total = 0
        limit = getattr(getattr(getattr(adapter, 'engine', None), 'config', None), 'budget', None)
        limit = limit.output_bytes if limit else 8 * 1024 * 1024
        while True:
            block = read(8192)
            if not block:
                break
            total += len(block)
            if total > limit:
                raise ValueError('Bridge output byte budget exceeded')
            write(block)
        return response.status, kind
    except BaseException as exc:
        primary = exc
        pending.cancel()
        raise
    finally:
        if connection is not None:
            try:
                adapter.release(connection, response, pending, reusable=False)
            except BaseException as secondary:
                if primary is not None:
                    primary.add_note('Adapter release failed: ' + str(secondary))
                else:
                    raise


class Bridge:
    def __init__(self, adapter, model, context, *, port=0, token, host='127.0.0.1'):
        validate_bind(host)
        if not isinstance(token, str) or len(token) < 24 or any(c in token for c in '\r\n'):
            raise ValueError('Explicit local access token of at least 24 characters required')
        self.adapter, self.model, self.context, self.token = adapter, model, context, token
        self.lock = threading.RLock()
        self.active = None
        self.active_guards = []
        self.requests = 0
        self.state = 'constructed'
        self.errors = []
        self.shutdown_thread = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'
            def log_message(self, *args):
                pass
            def setup(self):
                super().setup()
                self.connection.settimeout(30)
            def authorized(self):
                value = self.headers.get('Authorization', '')
                if hmac.compare_digest(value, 'Bearer ' + owner.token):
                    return True
                self.reply(401, {'error': {'message': 'Local access token required'}})
                return False
            def reply(self, status, value):
                raw = json.dumps(value, allow_nan=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                if self.path in ('/', '/assets/hydra-one.png'):
                    from importlib.resources import files
                    name = 'index.html' if self.path == '/' else 'hydra-one.png'
                    raw = files('hydra_addon').joinpath('assets', name).read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8' if name.endswith('.html') else 'image/png')
                    self.send_header('Content-Length', str(len(raw)))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers();self.wfile.write(raw);return
                if not self.authorized(): return
                if self.path == '/v1/models':
                    self.reply(200, dict(object='list', data=[dict(id=owner.model, object='model', owned_by='hydra-one',
                        active_context_length=owner.context, input_modalities=['text'])]))
                elif self.path in ('/health', '/metrics'):
                    self.reply(200, dict(state=owner.state, requests=owner.requests, active=owner.active is not None,
                        errors=list(owner.errors), collection_authorized=False))
                else:
                    self.reply(404, {'error': {'message': 'Endpoint not supported'}})
            def do_POST(self):
                if not self.authorized(): return
                if self.path != '/v1/chat/completions':
                    self.reply(404, {'error': {'message': 'Only Chat Completions supported'}});return
                pending = Pending(); finished = threading.Event(); sent = False
                watcher = timer = None
                with owner.lock:
                    if owner.state != 'running':
                        self.reply(503, {'error': {'message': 'Bridge unavailable'}});return
                    owner.active = pending
                try:
                    if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                        raise ValueError('One bounded Content-Length required')
                    size = int(self.headers['Content-Length'])
                    limit = owner.adapter.engine.config.budget.request_bytes
                    if not 0 < size <= limit:
                        raise ValueError('Request byte budget exceeded')
                    body = self.rfile.read(size)
                    if len(body) != size:
                        raise ValueError('Incomplete request body')
                    def headers(status, kind):
                        nonlocal sent
                        self.send_response(status);self.send_header('Content-Type', kind)
                        self.send_header('Connection', 'close');self.end_headers();sent = True
                    def write(block):
                        self.wfile.write(block);self.wfile.flush()
                    def disconnected():
                        while not finished.wait(.05):
                            try:
                                ready, _, _ = select.select([self.connection], [], [], 0)
                                if ready and not self.connection.recv(1, socket.MSG_PEEK):
                                    pending.cancel();return
                            except OSError:
                                pending.cancel();return
                    watcher = threading.Thread(target=disconnected, name='hydra-client-disconnect', daemon=True)
                    watcher.start()
                    timer = threading.Timer(owner.adapter.engine.config.timeout_s, pending.cancel)
                    timer.daemon = True;timer.start()
                    forward(owner.adapter, body, write, on_headers=headers, pending=pending)
                    owner.requests += 1
                except Exception as exc:
                    pending.cancel()
                    if getattr(owner.adapter.engine, 'state', None) == 'shutdown_uncertain':
                        owner.state = 'shutdown_uncertain'
                    owner.errors.append(dict(type=type(exc).__name__, message=str(exc)))
                    owner.errors[:] = owner.errors[-32:]
                    if not sent:
                        try:self.reply(400 if isinstance(exc, (ValueError, KeyError)) else 503, {'error': {'message': str(exc)}})
                        except OSError:pass
                    # Once bytes may have been sent, close; never retry or fabricate DONE.
                finally:
                    finished.set()
                    if timer is not None:
                        timer.cancel();timer.join(1)
                    if watcher is not None:watcher.join(1)
                    uncertain = any(t is not None and t.is_alive() for t in (timer, watcher))
                    with owner.lock:
                        if uncertain:
                            owner.state = 'shutdown_uncertain'
                            owner.active_guards = [t for t in (timer, watcher) if t is not None]
                        else:
                            owner.active = None
                    self.close_connection = True

        self.server = HTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05},
                                       name='hydra-http-listener', daemon=True)

    @property
    def address(self):
        return self.server.server_address

    def start(self):
        with self.lock:
            if self.state != 'constructed':raise ValueError('Bridge is not reusable')
            self.state = 'running'
            try:self.thread.start()
            except BaseException:
                self.state = 'shutdown_uncertain'
                raise
        return self.address

    def close(self, timeout=3):
        with self.lock:
            if self.state == 'closed':return True
            self.state = 'closing'
            if self.active is not None:self.active.cancel()
            # shutdown is allowed to wait, but not while holding this lifecycle lock.
            if self.thread.ident is not None and self.shutdown_thread is None:
                self.shutdown_thread = threading.Thread(target=self.server.shutdown, name='hydra-http-shutdown', daemon=True)
                self.shutdown_thread.start()
        deadline = time.monotonic() + timeout
        for thread in (self.shutdown_thread, self.thread):
            if thread is not None and thread.ident is not None:
                thread.join(max(0, deadline - time.monotonic()))
        for guard in self.active_guards:
            guard.join(max(0, deadline - time.monotonic()))
        if self.active_guards and not any(t.is_alive() for t in self.active_guards):
            self.active = None
            self.active_guards = []
        if self.thread.is_alive() or (self.shutdown_thread is not None and self.shutdown_thread.is_alive()) or self.active is not None:
            self.state = 'shutdown_uncertain';return False
        try:
            self.server.server_close()
            if self.server.fileno() != -1 or not self.adapter.close():
                self.state = 'shutdown_uncertain';return False
        except Exception as exc:
            self.errors.append(dict(type=type(exc).__name__, message=str(exc)))
            self.state = 'shutdown_uncertain';return False
        self.state = 'closed';return True
