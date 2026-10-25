"""Backend transport boundary. Capabilities are intentionally conservative."""
from dataclasses import dataclass, field
import http.client
import io
import select
import socket
import threading
import time
from typing import Protocol

from .baseline import validate_url


@dataclass
class Pending:
    timings: dict = field(default_factory=dict)
    connection: object = None
    transport: object = None
    cancelled: threading.Event = field(default_factory=threading.Event)

    def cancel(self):
        self.cancelled.set()
        transport = self.transport
        if transport:
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        if self.transport:
            self.transport.close()
            self.transport = None


class BackendAdapter(Protocol):
    def open(self, method: str, path: str, body: bytes | None, pending: Pending): ...


class InterruptibleReader(io.RawIOBase):
    """Poll before recv: Windows shutdown does not wake an already blocked recv."""
    def __init__(self, transport, pending, timeout_s):
        self.transport, self.pending, self.timeout_s = transport.dup(), pending, timeout_s

    def readable(self):
        return True

    def readinto(self, buffer):
        started = time.monotonic()
        while not self.pending.cancelled.is_set():
            if time.monotonic()-started > self.timeout_s:
                raise TimeoutError('Backend idle timeout')
            readable, _, _ = select.select([self.transport], [], [], .05)
            if readable:
                return self.transport.recv_into(buffer)
        raise OSError('Backend request cancelled')

    def close(self):
        self.transport.close()
        super().close()


class InterruptibleSocket:
    def __init__(self, transport, pending, timeout_s):
        self.transport, self.pending, self.timeout_s = transport, pending, timeout_s

    def __getattr__(self, name):
        return getattr(self.transport, name)

    def makefile(self, mode):
        if mode != 'rb':
            raise ValueError('Read-only HTTP socket wrapper')
        return io.BufferedReader(InterruptibleReader(self.transport, self.pending, self.timeout_s))


class LocalHTTPAdapter:
    """Attach to an explicitly initialized local backend; no lifecycle side effects."""
    def __init__(self, url, timeout_s=60, *, verified_keepalive=False):
        self.parsed = validate_url(url)
        self.timeout_s = timeout_s
        self.pool=[]
        self.pool_lock=threading.Lock()
        self.closed=False
        self.verified_keepalive=verified_keepalive
        self.capabilities = dict(chat=True, streaming=True, responses=False,
                                 model_loading=False, tensor_parallel=False,
                                 memory_control=False, backend_gpu_verified=False)

    def open(self, method, path, body, pending):
        started=time.perf_counter()
        connection=None
        with self.pool_lock:
            if self.closed:raise OSError('Adapter closed')
            while self.pool:
                candidate,saved=self.pool.pop()
                if time.monotonic()-saved<30:
                    connection=candidate
                    break
                candidate.close()
        reused=connection is not None
        if connection is None:
            connection = http.client.HTTPConnection(self.parsed.hostname, self.parsed.port or 80,
                                                     timeout=self.timeout_s)
        pending.connection = connection
        try:
            if not reused:connection.connect()
            pending.timings['connect_s']=time.perf_counter()-started
            pending.timings['reused_connection']=reused
            if reused:
                connection.sock.pending=pending
                pending.transport=connection.sock.transport
            else:
                pending.transport = connection.sock
                connection.sock = InterruptibleSocket(connection.sock, pending, self.timeout_s)
            if pending.cancelled.is_set():
                raise OSError('Cancelled before request')
            connection.request(method, path, body=body,
                               headers={'Content-Type':'application/json', 'Accept':'application/json, text/event-stream'})
            pending.timings['request_sent_s']=time.perf_counter()-started
            response = connection.getresponse()
            pending.timings['headers_s']=time.perf_counter()-started
            return connection, response
        except BaseException:
            connection.close()
            pending.close()
            raise

    def release(self,connection,response,pending,*,reusable=False):
        can_reuse=(self.verified_keepalive and reusable and not pending.cancelled.is_set() and response is not None
                   and response.isclosed() and not response.will_close and connection.sock is not None)
        if response:response.close()
        if can_reuse:
            with self.pool_lock:
                if not self.closed and len(self.pool)<16:
                    pending.transport=None
                    pending.connection=None
                    self.pool.append((connection,time.monotonic()))
                    return
        connection.close()
        pending.close()

    def close(self):
        with self.pool_lock:
            self.closed=True
            for connection,_ in self.pool:connection.close()
            self.pool.clear()
