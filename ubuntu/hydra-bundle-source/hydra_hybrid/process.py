"""Owned native child only. No process discovery, restart, kill or port allocation."""
import subprocess
import sys
import threading

from .core import BackendFailure


class OwnedProcess:
    def __init__(self, *, spawn=subprocess.Popen):
        self.spawn = spawn
        self.child = None
        self.state = 'idle'
        self.errors = []
        self.lock = threading.RLock()

    def start(self, argv, *, authorized=False, stdio=False):
        with self.lock:
            if not authorized:
                raise BackendFailure('Native launch requires separate explicit authorization')
            if self.child is not None or self.state != 'idle':
                raise BackendFailure('Process owner cannot be reused')
            self.state = 'starting'
            try:
                self.child = self.spawn(argv, stdin=subprocess.PIPE if stdio else subprocess.DEVNULL,
                                        stdout=subprocess.PIPE if stdio else subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, shell=False,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.state = 'running'
            except Exception as exc:
                self.state = 'shutdown_uncertain'
                self.errors.append(dict(type=type(exc).__name__, message=str(exc)))
                raise
            return self.child

    def close(self):
        with self.lock:
            if self.child is None:
                return self.state != 'shutdown_uncertain'
            try:
                if self.child.poll() is None:
                    self.child.terminate()
                    self.child.wait(timeout=3)
                if self.child.poll() is None:
                    self.state = 'shutdown_uncertain'
                    return False
                for name in ('stdin', 'stdout', 'stderr'):
                    stream = getattr(self.child, name, None)
                    if stream is not None:
                        stream.close()
            except Exception as exc:
                self.state = 'shutdown_uncertain'
                self.errors.append(dict(type=type(exc).__name__, message=str(exc)))
                return False
            self.child = None
            self.state = 'closed'
            return True


class StdioSidecar:
    """Optional Python process; construction and flag OFF never spawn anything.

    No request queue is hidden here. The caller owns JSONL stdin/stdout and must
    drain them. Interruptible cancellation is available via Engine.stream's Event;
    the sequential stdio protocol does not accept in-flight cancellation messages.
    """
    def __init__(self, *, spawn=subprocess.Popen):
        self.owner = OwnedProcess(spawn=spawn)

    def start(self, config, config_path, *, authorized=False):
        if not config.enabled:
            return None
        return self.owner.start([sys.executable, '-B', '-m', 'hydra_hybrid', 'stdio',
                                 '--config', str(config_path)], authorized=authorized, stdio=True)

    def close(self):
        return self.owner.close()
