"""Only one Strata dashboard per PC.

Two dashboards at once each hold their own model selection, MCP servers and harnesses, which
is how the 8088/8090 mix-ups started. The first dashboard to start claims a lock; a second
start on any other port is refused and points the user at the URL that already works.

Internal sidecars (the bounded candidate check, which needs its own server on a scratch port
while the real dashboard stays up) carry STRATA_VALIDATION_LEASE_TOKEN and skip the guard.
"""
import json
import http.client
import os
import socket
import urllib.request
from pathlib import Path

LOCK_NAME = 'dashboard.lock'
# The ports a dashboard may listen on, newest first: 8080 is the project default but is taken
# by another program on this PC.
DASHBOARD_PORTS = (8090, 8088, 8080)


class DashboardBusy(RuntimeError):
    pass


def lock_path(root):
    return Path(root) / 'data' / LOCK_NAME


def claimed_port(root):
    """The port claimed by a live dashboard, or None when nothing holds the claim."""
    path = lock_path(root)
    try:
        if not path.is_file() or path.is_symlink():
            return None
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    port, pid = record.get('port'), record.get('pid')
    if type(port) is not int or type(pid) is not int:
        return None
    if not _process_alive(pid, root, record.get('created_at')):
        return None
    return port


def claim_dashboard(root, port):
    """Claim the single-dashboard lock, refusing when another dashboard already holds it."""
    if os.environ.get('STRATA_VALIDATION_LEASE_TOKEN'):
        return None                                    # an internal sidecar, not a dashboard
    def busy(held):
        return DashboardBusy(
            f'Una dashboard Strata è già in esecuzione sulla porta {held}: '
            f'apri http://127.0.0.1:{held}/ invece di avviarne una seconda.')
    held = claimed_port(root)
    if held is not None:
        raise busy(held)
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    import psutil
    payload = json.dumps({'port': port, 'pid': os.getpid(), 'created_at': psutil.Process().create_time()})
    for _ in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            held = claimed_port(root)
            if held is not None:
                raise busy(held)
            try:
                path.unlink()
            except OSError:
                pass
            continue
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(payload)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return port
    raise DashboardBusy('Impossibile acquisire il lock della dashboard: riprova.')


def release_dashboard_claim(root):
    """Drop the claim on a clean shutdown; a claim from another pid is never touched."""
    path = lock_path(root)
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    if isinstance(record, dict) and record.get('pid') == os.getpid():
        path.unlink(missing_ok=True)


def existing_dashboard(ports=DASHBOARD_PORTS, timeout=2):
    """The port of a Strata dashboard already listening on loopback, or None."""
    for port in ports:
        if type(port) is not int or not 1 <= port <= 65535:
            continue
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=timeout) as response:
                health = json.load(response)
        except (OSError, ValueError, http.client.HTTPException):
            continue
        if isinstance(health, dict) and health.get('service') == 'strata':
            return port
    return None


def free_dashboard_port(preferred=None, extra=()):
    """A port this dashboard can bind, preferring the one already documented for it."""
    for port in (*( (preferred,) if preferred else () ), *DASHBOARD_PORTS, *extra):
        if type(port) is not int or not 1 <= port <= 65535:
            continue
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
        return port
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def _process_alive(pid, root=None, created_at=None):
    import psutil
    if type(pid) is not int:
        return False
    if pid == os.getpid():
        # This process is, by definition, alive. A claim written by this
        # process (the dashboard itself or a test harness) is not stale just
        # because the working directory or command line differs from the
        # dashboard layout.
        return True
    try:
        process = psutil.Process(pid)
        if not process.is_running():return False
        if created_at is not None and process.create_time()!=created_at:return False
        if root is not None:
            # Windows can reuse a dead dashboard PID for an unrelated process.
            if not process.name().lower().startswith('python'):return False
            if Path(process.cwd()).resolve()!=Path(root).resolve():return False
            args=process.cmdline()
            server=(Path(root)/'serve/server.py').resolve()
            if not any((arg=='serve.server' and index>0 and args[index-1]=='-m') or
                       (arg.replace('\\','/').endswith('serve/server.py') and (Path(root)/arg).resolve()==server)
                       for index,arg in enumerate(args)):return False
        return True
    except (psutil.Error, ValueError):
        return False
