"""Independent request ownership, conservative admission and event streaming."""
from dataclasses import dataclass
from collections import deque
import json
import threading
import time
import uuid

from .config import Config, Resources, host_resources, static_profile
from .protocol import validate_request, cache_request


class BackendFailure(RuntimeError):
    def __init__(self, message, *, retry_safe=False):
        super().__init__(message)
        self.retry_safe = retry_safe


class Cancelled(BackendFailure):
    pass


class ResourceDenied(BackendFailure):
    pass


@dataclass(frozen=True)
class Event:
    kind: str
    data: object = None


@dataclass(eq=False)
class Lease:
    id: str
    owner: object
    released: bool = False


class Ledger:
    """Only active leases reside here; a released handle remains idempotent."""
    def __init__(self, capacity):
        self.capacity = capacity
        self.lock = threading.RLock()
        self.rows = {}

    @property
    def active(self):
        with self.lock:
            return len(self.rows)

    def reserve(self):
        with self.lock:
            if self.active >= self.capacity:
                raise ResourceDenied('Concurrency budget exhausted')
            key = uuid.uuid4().hex
            lease = Lease(key, self)
            self.rows[key] = lease
            return lease

    def release(self, key):
        with self.lock:
            if not isinstance(key, Lease) or key.owner is not self:
                raise ValueError('Unknown lease owner')
            if key.released:
                return
            if self.rows.get(key.id) is not key:
                raise ValueError('Lease identity mismatch')
            key.released = True
            del self.rows[key.id]


class Engine:
    def __init__(self, config=Config(), backend_factory=None, resources=host_resources, *, fallback_factory=None, clock=time.monotonic):
        self.config = config
        self.config_fingerprint = static_profile(config)['fingerprint']
        self.factory = backend_factory
        self.fallback_factory = fallback_factory
        self.resources = resources
        self.clock = clock
        self.ledger = Ledger(config.max_concurrent)
        self.lock = threading.RLock()
        self.close_lock = threading.Lock()
        self.backends = {}
        self.state = 'idle' if config.enabled else 'disabled'
        self.failures = 0
        self.metrics = deque(maxlen=256)
        self.errors = deque(maxlen=128)

    def status(self):
        with self.lock:
            return dict(state=self.state, active=self.ledger.active, failures=self.failures,
                        collection_authorized=False, real_inference_verified=False,
                        nvme_streaming='unavailable', remote='unavailable', errors=list(self.errors))

    def _check(self, cancel, deadline):
        if cancel.is_set():
            raise Cancelled('Request cancelled')
        if self.clock() >= deadline:
            raise TimeoutError('Request deadline expired')

    def _resources(self, active, replicas=None):
        c = self.config
        r = self.resources()
        if not isinstance(r, Resources) or r.host_available_bytes is None:
            raise ResourceDenied('Available host memory is unknown')
        if r.cpu_available_threads is not None and c.threads > r.cpu_available_threads:
            raise ResourceDenied('CPU thread budget exceeds observed affinity/capacity')
        host = c.host_required_bytes * (max(1, len(self.backends)) if replicas is None else replicas) + c.request_memory_bytes * active
        if host > c.budget.host_limit_bytes or r.host_available_bytes < c.budget.host_reserve_bytes + host:
            raise ResourceDenied('Host memory budget or OS reserve exceeded')
        if c.gpu_layers:
            if not c.vram_required_bytes or r.vram_available_bytes is None:
                raise ResourceDenied('GPU placement requires explicit requirement and observed available VRAM')
            vram = c.vram_required_bytes * (max(1, len(self.backends)) if replicas is None else replicas) + c.request_vram_bytes * active
            if vram + c.budget.vram_reserve_bytes > min(c.budget.vram_limit_bytes, r.vram_available_bytes):
                raise ResourceDenied('VRAM admission budget exceeded')

    def _request(self, value):
        if not isinstance(value, dict):
            raise ValueError('Chat request object required')
        try:
            raw = json.dumps(value, allow_nan=False).encode('utf-8')
        except (TypeError, ValueError) as exc:
            raise ValueError('JSON-compatible finite request required') from exc
        if len(raw) > self.config.budget.request_bytes:
            raise ResourceDenied('Request exceeds byte budget')
        result = cache_request(json.loads(raw), self.config.prompt_cache_policy)
        validate_request(result)
        if result.get('model') != self.config.model:
            raise ValueError('Model identity mismatch')
        if not isinstance(result.get('messages'), list):
            raise ValueError('Messages array required')
        for message in result['messages']:
            if not isinstance(message, dict) or message.get('role') not in ('system', 'developer', 'user', 'assistant', 'tool'):
                raise ValueError('Invalid chat message')
        tokens = result.get('max_tokens', 128)
        if type(tokens) is not int or tokens <= 0:
            raise ValueError('Positive max_tokens required')
        # Conservative byte-based admission, not a claim of tokenizer equivalence.
        if len(raw) + tokens + 64 * len(result['messages']) > self.config.context:
            raise ValueError('Conservative context admission bound exceeded')
        result['stream'] = True
        return result

    def stream(self, request, cancel=None):
        cancel = cancel if cancel is not None else threading.Event()
        started = self.clock()
        deadline = started + self.config.timeout_s
        lease = None
        output_started = False
        first = None
        count = 0
        success = False
        secondary = []
        outcome = 'failed'
        iterator = None
        backend = None
        request_id = uuid.uuid4().hex
        executed_route = None
        usage = None
        try:
            with self.lock:
                if not self.config.enabled:
                    raise BackendFailure('Engine disabled')
                if self.state in ('draining', 'closed', 'shutdown_uncertain'):
                    raise BackendFailure('Engine not accepting requests: ' + self.state)
                if self.failures >= self.config.breaker_failures:
                    raise BackendFailure('Circuit open; explicit operator reset required')
                data = self._request(request)
                self._check(cancel, deadline)
                self._resources(self.ledger.active + 1)
                lease = self.ledger.reserve()
                self.state = 'ready'
            for route in ('primary', 'fallback'):
                try:
                    self._check(cancel, deadline)
                    with self.lock:
                        factory = self.factory if route == 'primary' else self.fallback_factory
                        if factory is None:
                            raise BackendFailure('No configured backend', retry_safe=True)
                        self._resources(self.ledger.active, max(1, len(self.backends) + int(route not in self.backends)))
                        if route not in self.backends:
                            self.backends[route] = factory()
                        backend = self.backends[route]
                    iterator = iter(backend.stream(json.loads(json.dumps(data)), cancel, deadline))
                    executed_route = route
                    for event in iterator:
                        self._check(cancel, deadline)
                        self._resources(self.ledger.active)
                        if not isinstance(event, Event) or event.kind not in ('content', 'tool', 'usage', 'done'):
                            raise BackendFailure('Invalid backend event')
                        if event.kind == 'content' and not isinstance(event.data, str):
                            raise BackendFailure('Invalid content delta')
                        if event.kind == 'usage':
                            if not isinstance(event.data, dict):
                                raise BackendFailure('Invalid usage object')
                            for name in ('completion_tokens','prompt_tokens','total_tokens'):
                                value = event.data.get(name)
                                if value is not None and (type(value) is not int or value < 0):
                                    raise BackendFailure('Invalid backend token count')
                            details = event.data.get('prompt_tokens_details')
                            if details is not None:
                                if not isinstance(details, dict):
                                    raise BackendFailure('Invalid prompt token details')
                                cached = details.get('cached_tokens')
                                if cached is not None and (type(cached) is not int or cached < 0 or
                                        (event.data.get('prompt_tokens') is not None and cached > event.data['prompt_tokens'])):
                                    raise BackendFailure('Invalid cached token count')
                            if usage is not None and usage != event.data:
                                raise BackendFailure('Conflicting usage observations')
                            usage = dict(event.data)
                        try:
                            count += len(json.dumps(event.data, allow_nan=False).encode('utf-8'))
                        except (ValueError, TypeError) as exc:
                            raise BackendFailure('Non-JSON backend event') from exc
                        if count > self.config.budget.output_bytes:
                            raise ResourceDenied('Output byte budget exceeded')
                        output_started = True
                        if first is None and event.kind in ('content', 'tool'):
                            first = self.clock() - started
                        if event.kind == 'done':
                            success = True
                            outcome = 'completed'
                        yield event
                        if success:
                            break
                    if not success:
                        raise BackendFailure('Incomplete backend stream')
                    break
                except BackendFailure as exc:
                    if route == 'primary' and self.fallback_factory is not None and exc.retry_safe and not output_started and not cancel.is_set() and not isinstance(exc, (Cancelled, ResourceDenied)):
                        if iterator is not None and hasattr(iterator, 'close'):
                            iterator.close()
                            iterator = None
                        self.errors.append(dict(type=type(exc).__name__, message=str(exc), action='fallback_before_output'))
                        continue
                    raise
        except Cancelled:
            outcome = 'cancelled'
            raise
        except GeneratorExit:
            outcome = 'consumer_closed'
            raise
        except Exception as exc:
            if isinstance(exc, TimeoutError):
                outcome = 'timeout'
            with self.lock:
                if lease is not None and not isinstance(exc, (ResourceDenied, ValueError)):
                    self.failures += 1
                    if self.state not in ('draining', 'closed', 'shutdown_uncertain'):
                        self.state = 'degraded'
                self.errors.append(dict(type=type(exc).__name__, message=str(exc)))
            raise
        finally:
            try:
                if iterator is not None and hasattr(iterator, 'close'):
                    iterator.close()
                if backend is not None and getattr(backend, 'cleanup_uncertain', False):
                    secondary.append(dict(type='TransportCleanupUncertain', message='Backend retained an unresolved transport'))
                    with self.lock:
                        self.state = 'shutdown_uncertain'
            except Exception as exc:
                secondary.append(dict(type=type(exc).__name__, message=str(exc)))
                with self.lock:
                    self.state = 'shutdown_uncertain'
            finally:
                if lease is not None:
                    self.ledger.release(lease)
                with self.lock:
                    if secondary:
                        outcome = 'cleanup_uncertain'
                    self.metrics.append(dict(wall_s=max(0, self.clock() - started), ttft_s=first,
                        outcome=outcome, secondary_errors=secondary,
                        request_id=request_id, config_fingerprint=self.config_fingerprint,
                        route=executed_route, timing_contract='hybrid-engine-service-v1',
                        output_tokens=usage.get('completion_tokens') if usage is not None and success and not secondary else None,
                        usage_provenance='backend_reported_unattested' if usage is not None else None,
                        cached_prompt_tokens=(usage.get('prompt_tokens_details') or {}).get('cached_tokens') if usage is not None and success and not secondary else None,
                        cache_observation_source='backend_usage_unattested' if usage is not None and isinstance(usage.get('prompt_tokens_details'), dict) and usage['prompt_tokens_details'].get('cached_tokens') is not None else None,
                        ram_peak_bytes=None, vram_peak_bytes=None, cpu_utilization=None,
                        gpu_utilization=None, tier_transfer_bytes=None, collection_authorized=False))
                    if success and not secondary:
                        self.failures = 0
            if secondary and success:
                raise BackendFailure('Stream completed but transport cleanup is uncertain')

    def close(self):
        if not self.close_lock.acquire(blocking=False):
            return False
        try:
            return self._close()
        finally:
            self.close_lock.release()

    def _close(self):
        with self.lock:
            if self.ledger.active:
                self.state = 'draining'
                return False
            if self.state == 'closed':
                return True
            self.state = 'draining'
            backends = list(self.backends.values())
        errors = []
        for backend in backends:
            try:
                backend.close()
            except Exception as exc:
                errors.append(dict(type=type(exc).__name__, message=str(exc)))
        with self.lock:
            self.errors.extend(errors)
            self.state = 'shutdown_uncertain' if errors else 'closed'
            return not errors
