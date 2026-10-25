"""Only one Strata dashboard per PC.

Two dashboards at once each hold their own model selection, MCP servers and harnesses, which
is how the 8088/8090 mix-ups started. The first dashboard to start claims a lock; a second
start on any other port is refused and points the user at the URL that already works.

Internal sidecars (the bounded candidate check, which needs its own server on a scratch port
while the real dashboard stays up) carry STRATA_VALIDATION_LEASE_TOKEN and skip the guard.
"""
import json
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
    if not _process_alive(pid):
        path.unlink(missing_ok=True)
        return None
    return port


def claim_dashboard(root, port):
    """Claim the single-dashboard lock, refusing when another dashboard already holds it."""
    if os.environ.get('STRATA_VALIDATION_LEASE_TOKEN'):
        return None                                    # an internal sidecar, not a dashboard
    held = claimed_port(root)
    if held is not None:
        raise DashboardBusy(
            f'Una dashboard Strata è già in asecuzione sulla porta {held}: '
            f'apri http://127.0.0.1:{held}/ invece di avviarne una seconda.')
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'port': port, 'pid': os.getpid()}), encoding='utf-8')
    return port


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
        except (OSError, ValueError):
            continue
        except Exception:
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


def _process_alive(pid):
    import psutil
    try:
        return psutil.Process(pid).is_running()
    except (psutil.Error, ValueError):
        return False
