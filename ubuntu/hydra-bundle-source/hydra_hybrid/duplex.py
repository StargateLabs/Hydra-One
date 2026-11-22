"""Opt-in duplex JSONL. Engine remains the sole admission/lease authority."""
from dataclasses import asdict
import json
import math
import threading
import time


class Session:
    def __init__(self, destination, engine, drain_timeout):
        if not isinstance(drain_timeout, (int, float)) or not math.isfinite(drain_timeout) or drain_timeout <= 0:
            raise ValueError('Finite positive drain timeout required')
        self.destination = destination
        self.engine = engine
        self.drain_timeout = drain_timeout
        self.lock = threading.RLock()
        self.output_lock = threading.Lock()
        self.workers = {}
        self.state = 'active'
        self.errors = []
        self.output_failed = False

    def send(self, row):
        with self.output_lock:
            if self.output_failed:
                return
            try:
                self.destination.write(json.dumps(row, allow_nan=False) + '\n')
                self.destination.flush()
            except Exception as exc:
                self.output_failed = True
                self.errors.append(type(exc).__name__ + ': ' + str(exc))
                self.cancel_all()

    def cancel_all(self):
        with self.lock:
            for row in self.workers.values():
                row['cancel'].set()

    def worker(self, ident, request, cancel):
        iterator = None
        try:
            iterator = self.engine.stream(request, cancel)
            for event in iterator:
                if self.output_failed:
                    break
                self.send(dict(id=ident, type='event', event=asdict(event)))
        except Exception as exc:
            self.send(dict(id=ident, type='error', error_type=type(exc).__name__, message=str(exc)))
        finally:
            if iterator is not None:
                try:
                    iterator.close()
                except Exception as exc:
                    with self.lock:
                        self.workers[ident]['cleanup_error'] = str(exc)
                    self.errors.append('Iterator cleanup: ' + str(exc))

    def dispatch(self, ident, request):
        with self.lock:
            if self.state != 'active' or self.output_failed:
                raise ValueError('Channel not active; dispatch refused')
            if ident in self.workers:
                raise ValueError('Duplicate request id; replay refused')
            if len(self.workers) >= 4096:
                raise ValueError('Channel identity budget exhausted; open a new channel')
            # This bounds channel threads only. Engine owns actual resource leases.
            if sum(row['thread'].is_alive() for row in self.workers.values()) >= self.engine.config.max_concurrent:
                raise ValueError('Channel busy; no request queued')
            cancel = threading.Event()
            thread = threading.Thread(target=self.worker, args=(ident, request, cancel), name='hybrid-jsonl-' + ident, daemon=True)
            row = dict(thread=thread, cancel=cancel, start_resolved=False, start_error=None, cleanup_error=None)
            self.workers[ident] = row  # Ownership exists before start, including start-then-raise.
            try:
                thread.start()
            except BaseException as exc:
                row['start_error'] = type(exc).__name__ + ': ' + str(exc)
                cancel.set()
                raise
            finally:
                row['start_resolved'] = True

    def close(self):
        with self.lock:
            self.state = 'closing'
            self.cancel_all()
            rows = list(self.workers.values())
        deadline = time.monotonic() + self.drain_timeout
        unknown = False
        for row in rows:
            thread = row['thread']
            try:
                if thread.ident is not None:
                    thread.join(max(0, deadline - time.monotonic()))
                if not row['start_resolved'] or thread.is_alive() or row['cleanup_error']:
                    unknown = True
            except Exception as exc:
                self.errors.append('Worker observation: ' + str(exc))
                unknown = True
        if not unknown:
            try:
                unknown = not self.engine.close()
            except Exception as exc:
                self.errors.append('Engine cleanup: ' + str(exc))
                unknown = True
        self.state = 'shutdown_uncertain' if unknown else 'closed'
        return dict(state=self.state, output_failed=self.output_failed, errors=list(self.errors),
                    tracked_requests=len(self.workers), collection_authorized=False)


def serve(source, destination, engine, *, drain_timeout=2):
    if getattr(engine, '_duplex_session', None) is not None:
        raise ValueError('Engine already owned by a duplex session')
    session = Session(destination, engine, drain_timeout)
    engine._duplex_session = session  # Retains registry for explicit drain after uncertainty.
    try:
        while not session.output_failed:
            line = source.readline(engine.config.budget.request_bytes + 1)
            if not line:
                break
            ident = None
            try:
                if not line.endswith('\n') or len(line.encode('utf-8')) > engine.config.budget.request_bytes:
                    raise ValueError('Oversized or incomplete frame; close channel')
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('JSON object required')
                ident = message.get('id')
                if not isinstance(ident, str) or not ident or len(ident) > 128:
                    raise ValueError('Bounded nonempty request id required')
                kind = message.get('type')
                if kind == 'health':
                    session.send(dict(id=ident, type='health', data=engine.status()))
                elif kind == 'cancel':
                    target = message.get('target')
                    if not isinstance(target, str):
                        raise ValueError('String cancel target required')
                    with session.lock:
                        row = session.workers.get(target)
                        if row is not None:
                            row['cancel'].set()
                    session.send(dict(id=ident, type='cancel_ack', target=target, signalled=row is not None,
                                      remote_release_verified=False))
                elif kind == 'request':
                    if not isinstance(message.get('request'), dict):
                        raise ValueError('Request object required')
                    session.dispatch(ident, message['request'])
                else:
                    raise ValueError('Supported types: request, cancel, health')
            except Exception as exc:
                session.send(dict(id=ident, type='error', error_type=type(exc).__name__, message=str(exc)))
                if not line.endswith('\n'):
                    break
    finally:
        result = session.close()
        if result['state'] != 'closed':
            session.send(dict(id=None, type='shutdown_uncertain', data=result))
    return result
