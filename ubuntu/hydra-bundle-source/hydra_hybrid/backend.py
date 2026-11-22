"""llama.cpp boundary. Existing HTTP transport is imported only on explicit live use."""
import hashlib
import json
from pathlib import Path
import re
import threading
import time

from .core import BackendFailure, Cancelled, Engine, Event, ResourceDenied
from .protocol import StreamContract, strict_json, cache_request


def inspect_backend(config):
    """Offline inspection never starts a runtime, even to obtain --version."""
    try:
        return _inspect_backend(config)
    except OSError as exc:
        return dict(state='unavailable', reason='File inspection failed', error_code='file_io_error',
                    error_type=type(exc).__name__, hardware_verified=False,
                    revision=config.backend_revision or None, capabilities={})


def _inspect_backend(config):
    result = dict(state='unavailable', reason=None, backend='llama.cpp', license='MIT',
        error_code=None,
        revision=config.backend_revision or None, revision_provenance='operator declaration',
        binary_hash_verified=False, model_hash_verified=False, hardware_verified=False,
        capabilities=dict(cpu='declared_unverified', hip='unknown', vulkan='unknown',
            static_layer_offload='declared_unverified', nvme_streaming='unsupported', remote='unsupported',
            deepseek_v4='unknown', paged_attention='unknown'), available_vram_bytes=None)
    if not config.enabled:
        result.update(state='disabled', reason='Feature flag OFF; no files or native dependencies inspected')
        return result
    for label, path, digest in (('binary', config.binary, config.binary_sha256), ('model', config.model_path, config.model_sha256)):
        if not path or not Path(path).is_file():
            result['reason'] = 'Missing explicit ' + label + ' file'
            result['error_code'] = 'missing_' + label
            return result
        if not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
            result['reason'] = 'Pinned SHA256 required for ' + label
            result['error_code'] = label + '_hash_required'
            return result
        with Path(path).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest.lower():
                result['reason'] = label + ' hash mismatch'
                result['error_code'] = label + '_hash_mismatch'
                return result
        result[label + '_hash_verified'] = True
    if not re.fullmatch(r'(?:[0-9a-fA-F]{40}|b[0-9]+)', config.backend_revision):
        result['reason'] = 'Explicit backend commit or build tag required'
        result['error_code'] = 'revision_required'
        return result
    with Path(config.model_path).open('rb') as stream:
        if stream.read(4) != b'GGUF':
            result['reason'] = 'Only explicit GGUF files supported'
            result['error_code'] = 'unsupported_format'
            return result
    result.update(state='prepared', reason='File identities checked; architecture, DLL closure and real inference NOT_TESTED')
    return result


def launch_plan(config, *, port):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Explicit unprivileged loopback port required')
    argv = [config.binary, '--model', config.model_path, '--alias', config.model,
            '--host', '127.0.0.1', '--port', str(port), '--ctx-size', str(config.context * config.max_concurrent),
            '--parallel', str(config.max_concurrent), '--threads', str(config.threads),
            '--n-gpu-layers', str(config.gpu_layers), '--device', 'none' if not config.gpu_layers else 'ROCm0']
    options = []
    for flag, value in (('--batch-size',config.batch_size),('--ubatch-size',config.ubatch_size)):
        if value is not None:options.extend([flag,str(value)])
    if config.load_mode != 'inherit':options.extend(['--load-mode',config.load_mode])
    if config.lazy_mode != 'inherit':options.extend(['--lazy-mode',config.lazy_mode])
    if config.speculative != 'none':options.extend(['--spec-type',config.speculative])
    if options:
        # Bound to local help evidence, NOT a generic capability of all b11541 builds.
        observed = 'c9e00dde9fa215227c39eaee98dffa3cb6db1778651ac2fd8b72b0e129703d83'
        if config.binary_sha256.lower() != observed:
            raise ValueError('Native options require the exact observed binary identity; prepare() must still verify the file')
    return argv + options


class HTTPBackend:
    def __init__(self, config, *, transport_factory=None, clock=time.monotonic):
        self.config = config
        self.transport_factory = transport_factory
        self.transport = None
        self.clock = clock
        self.cleanup_uncertain = False
        self.prepared_identity = None
        self.lock = threading.RLock()
        self.timers = set()
        self.closed = False

    def prepare(self):
        """Explicit offline file verification, outside every request deadline."""
        self.prepared_identity = inspect_backend(self.config)
        return self.prepared_identity

    def _transport(self, remaining):
        # Serialize creation only, never hold this lock across HTTP I/O.
        with self.lock:
            return self._create_transport(remaining)

    def _create_transport(self, remaining):
        if self.closed:
            raise BackendFailure('Backend already closed')
        if self.cleanup_uncertain:
            raise BackendFailure('Transport cleanup uncertain; backend quarantined')
        if not self.config.enabled or not self.config.live_io_authorized:
            raise BackendFailure('Live transport is disabled', retry_safe=True)
        if self.transport is None:
            if self.transport_factory is not None:
                self.transport = self.transport_factory()
            else:
                if self.prepared_identity is None or self.prepared_identity['state'] != 'prepared':
                    raise BackendFailure('Explicit offline backend.prepare() required before live requests', retry_safe=True)
                from hydra_lab.adapters import LocalHTTPAdapter
                # Reused transport keeps the configured ceiling. Per-operation timer
                # and Pending cancel enforce the caller's shorter deadline.
                self.transport = LocalHTTPAdapter(self.config.backend_url, self.config.timeout_s)
        return self.transport

    def health(self, *, cancel=None, deadline=None):
        """Explicit GET only. Ready is not proof of model/process/GPU identity."""
        if not self.config.enabled or not self.config.live_io_authorized:
            return dict(state='disabled', model_identity_verified=False, hardware_verified=False)
        from hydra_lab.adapters import Pending
        cancel = cancel if cancel is not None else threading.Event()
        deadline = self.clock() + self.config.timeout_s if deadline is None else min(deadline, self.clock()+self.config.timeout_s)
        if cancel.is_set():
            raise Cancelled('Health check cancelled before dispatch')
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError('Health deadline expired')
        pending = Pending(cancelled=cancel)
        expired = threading.Event()
        def expire():
            expired.set()
            pending.cancel()
        timer = threading.Timer(remaining, expire)
        timer.daemon = True
        # Admission and timer ownership are atomic with respect to close().
        with self.lock:
            transport = self._create_transport(remaining)
            self.timers.add(timer)
        connection = response = primary = None
        try:
            timer.start()
            if expired.is_set() or self.clock() >= deadline:
                raise TimeoutError('Health deadline expired before dispatch')
            if cancel.is_set():
                raise Cancelled('Health check cancelled before dispatch')
            connection, response = transport.open('GET', '/health', None, pending)
            if response.getheader('Content-Type', '').split(';')[0].strip() != 'application/json':
                raise BackendFailure('Health response must be JSON')
            raw = response.read(65537)
            if not isinstance(raw, bytes) or len(raw) > 65536:
                raise BackendFailure('Health response exceeds limit')
            try:
                value = strict_json(raw)
                if not isinstance(value, dict):
                    raise ValueError('Health object required')
            except (ValueError, TypeError, RecursionError) as exc:
                raise BackendFailure('Malformed health response') from exc
            if expired.is_set() or self.clock() >= deadline:
                raise TimeoutError('Health deadline expired')
            if cancel.is_set():
                raise Cancelled('Health check cancelled')
            error = value.get('error')
            state = 'unavailable'
            if response.status == 200 and value.get('status') == 'ok':
                state = 'ready'
            elif response.status == 503 and isinstance(error, dict) and error.get('message') == 'Loading model':
                state = 'loading'
            return dict(state=state, http_status=response.status, model_identity_verified=False,
                        hardware_verified=False, source='backend_health_response_unattested')
        except BaseException as exc:
            primary = exc
            if isinstance(exc, Exception):
                if expired.is_set() or self.clock() >= deadline:
                    primary = TimeoutError('Health deadline expired')
                elif cancel.is_set():
                    primary = Cancelled('Health check cancelled')
            if primary is not exc:
                raise primary from exc
            raise
        finally:
            self._finish_operation(timer, transport, connection, response, pending, primary)

    def stream(self, request, cancel, deadline):
        request = cache_request(request, self.config.prompt_cache_policy)
        contract = StreamContract(request)
        if not self.config.enabled or not self.config.live_io_authorized:
            raise BackendFailure('Live transport is disabled', retry_safe=True)
        from hydra_lab.adapters import Pending
        if cancel.is_set():
            raise Cancelled('Cancelled before backend dispatch')
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError('Backend deadline expired')
        transport = self._transport(remaining)
        pending = Pending(cancelled=cancel)
        connection = response = None
        expired = threading.Event()
        def expire():
            expired.set()
            pending.cancel()
        timer = threading.Timer(min(remaining, self.config.timeout_s), expire)
        timer.daemon = True
        size = 0
        data_lines = []
        primary = None
        with self.lock:
            if self.closed:
                raise BackendFailure('Backend already closed')
            self.timers.add(timer)
        try:
            timer.start()
            body = dict(request, stream=True)
            if expired.is_set() or self.clock() >= deadline:
                raise TimeoutError('Backend deadline expired before dispatch')
            if cancel.is_set():
                raise Cancelled('Backend request cancelled before dispatch')
            connection, response = transport.open('POST', '/v1/chat/completions', json.dumps(body, allow_nan=False).encode(), pending)
            if response.status != 200:
                # Conservatively do not retry: remote processing is not disproven.
                raise BackendFailure('Backend HTTP status ' + str(response.status))
            if response.getheader('Content-Type', '').split(';')[0].strip() != 'text/event-stream':
                raise BackendFailure('Expected SSE response')
            while True:
                if cancel.is_set():
                    raise Cancelled('Backend request cancelled')
                if self.clock() >= deadline:
                    raise TimeoutError('Backend deadline expired')
                line = response.readline(65537)
                if not isinstance(line, bytes) or len(line) > 65536:
                    raise BackendFailure('Invalid or oversized SSE line')
                if not line:
                    raise BackendFailure('Backend stream ended without DONE')
                size += len(line)
                if size > self.config.budget.output_bytes:
                    raise ResourceDenied('Backend SSE byte budget exceeded')
                if line.strip():
                    if line.startswith(b'data:'):
                        data_lines.append(line[5:].strip())
                    continue
                if not data_lines:
                    continue
                raw = b'\n'.join(data_lines)
                data_lines.clear()
                if raw == b'[DONE]':
                    try:
                        contract.finish()
                    except (ValueError, TypeError, RecursionError) as exc:
                        raise BackendFailure('Invalid completed output contract') from exc
                    yield Event('done')
                    return
                try:
                    value = strict_json(raw)
                    if not isinstance(value, dict) or 'error' in value:
                        raise ValueError('Invalid SSE object')
                    choices = value.get('choices', [])
                    if not isinstance(choices, list):
                        raise ValueError('Invalid choices')
                    for choice in choices:
                        contract.observe(choice)
                        delta = choice.get('delta', {})
                        if not isinstance(delta, dict):
                            raise ValueError('Invalid delta')
                        if delta.get('content') is not None:
                            if not isinstance(delta['content'], str):
                                raise ValueError('Invalid content')
                            yield Event('content', delta['content'])
                        if delta.get('tool_calls') is not None:
                            if not isinstance(delta['tool_calls'], list):
                                raise ValueError('Invalid tool_calls')
                            yield Event('tool', delta['tool_calls'])
                    if value.get('usage') is not None:
                        yield Event('usage', value['usage'])
                except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError) as exc:
                    raise BackendFailure('Malformed SSE payload') from exc
        except BaseException as exc:
            primary = exc
            # The historical transport reports interrupted reads as OSError.
            # Normalize only here, leaving the shared adapter untouched.
            if isinstance(exc, Exception):
                if expired.is_set() or self.clock() >= deadline:
                    primary = TimeoutError('Backend request deadline expired')
                elif cancel.is_set() and not isinstance(exc, Cancelled):
                    primary = Cancelled('Backend request cancelled')
            if primary is not exc:
                raise primary from exc
            raise
        finally:
            self._finish_operation(timer, transport, connection, response, pending, primary)

    def _finish_operation(self, timer, transport, connection, response, pending, primary):
        """One cleanup path for explicit health and generation transport."""
        cleanup_errors = []
        timer_drained = False
        try:
            timer.cancel()
            if timer.ident is not None:
                timer.join(timeout=.5)
            if timer.is_alive():
                raise BackendFailure('Deadline timer has not drained')
            timer_drained = True
        except Exception as secondary:
            cleanup_errors.append(secondary)
        try:
            if connection is not None:
                transport.release(connection, response, pending, reusable=False)
            else:
                pending.close()
        except Exception as secondary:
            cleanup_errors.append(secondary)
        # Keep ownership until the entire release attempt is reconciled.
        with self.lock:
            if cleanup_errors:
                self.cleanup_uncertain = True
            if timer_drained:
                self.timers.discard(timer)
        if cleanup_errors:
            if primary is not None:
                for secondary in cleanup_errors:
                    primary.add_note('Secondary transport cleanup: ' + str(secondary))
            else:
                raise BackendFailure('Transport cleanup uncertain: ' + '; '.join(map(str, cleanup_errors))) from cleanup_errors[0]

    def close(self):
        with self.lock:
            if self.timers:
                raise BackendFailure('Active or uncertain request timer retains backend ownership')
            self.closed = True
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                self.cleanup_uncertain = True
                raise
        if self.cleanup_uncertain:
            raise BackendFailure('Cannot prove cleanup of previously uncertain transport')


class HydraAdapter:
    """Opt-in raw open/release facade, independent of every experimental gateway.

    Do not nest it inside Engine.stream: each entry point has exactly one ledger.
    This raw facade preserves upstream bytes/status and never performs retries.
    """
    def __init__(self, config, *, resources=None, transport_factory=None):
        options = {} if resources is None else dict(resources=resources)
        self.engine = Engine(config, **options)
        self.backend = HTTPBackend(config, transport_factory=transport_factory)
        self.pending = {}
        self.capabilities = dict(chat=True, streaming=True, responses=False, model_loading=False,
                                 tensor_parallel=False, memory_control=False, backend_gpu_verified=False)

    def prepare(self):
        return self.backend.prepare()

    def open(self, method, path, body, pending):
        e = self.engine
        with e.lock:
            if not e.config.enabled or not e.config.live_io_authorized:
                raise BackendFailure('Hybrid adapter disabled', retry_safe=True)
            if e.state in ('draining', 'closed', 'shutdown_uncertain'):
                raise BackendFailure('Adapter not accepting requests')
            if method != 'POST' or path != '/v1/chat/completions':
                raise ValueError('Only Chat Completions supported by hybrid raw adapter')
            if not isinstance(body, bytes) or len(body) > e.config.budget.request_bytes:
                raise ValueError('Bounded JSON bytes required')
            normalized = e._request(json.loads(body))
            body = json.dumps(normalized, allow_nan=False).encode()
            if len(body) > e.config.budget.request_bytes:
                raise ValueError('Normalized request exceeds byte budget')
            if pending.cancelled.is_set():
                raise Cancelled('Cancelled before admission')
            if id(pending) in self.pending:
                raise ValueError('Pending already owns a lease')
            e._resources(e.ledger.active + 1)
            lease = e.ledger.reserve()
            self.pending[id(pending)] = dict(lease=lease, state='reserved')
        try:
            return self.backend._transport(e.config.timeout_s).open(method, path, body, pending)
        except BaseException:
            with e.lock:
                self.pending.pop(id(pending), None)
                e.ledger.release(lease)
            raise

    def release(self, connection, response, pending, *, reusable=False):
        e = self.engine
        with e.lock:
            row = self.pending.get(id(pending))
            if row is None or row['state'] == 'completing':
                return
            row['state'] = 'completing'
            lease = row['lease']
        try:
            self.backend.transport.release(connection, response, pending, reusable=False)
        except BaseException:
            with e.lock:
                e.state = 'shutdown_uncertain'
                self.backend.cleanup_uncertain = True
            raise
        finally:
            with e.lock:
                self.pending.pop(id(pending), None)
                e.ledger.release(lease)

    def close(self):
        with self.engine.lock:
            if self.engine.ledger.active:
                self.engine.state = 'draining'
                return False
            self.engine.backends['primary'] = self.backend
        return self.engine.close()
