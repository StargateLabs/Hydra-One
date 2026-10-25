"""Tell the user an applied update needs a restart, and never re-announce it.

An update that changes the engine or a runtime is only *selected* while it is applied: the
running process keeps the old code until it starts again. This module records what was
selected so the interface can offer the restart once, and remembers the applied version so
its notification never comes back.
"""
import json
import os
import sys
from pathlib import Path

MARKER = 'update-restart-pending.json'


def marker_path(root):
    return Path(root) / 'data' / MARKER


def _read(root):
    path = marker_path(root)
    try:
        if not path.is_file() or path.is_symlink():
            return {}
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def mark_restart_pending(root, component, version, port=None):
    """Record that this selection only takes effect after a restart."""
    record = _read(root)
    applied = dict(record.get('applied') or {})
    applied[component] = version
    record['applied'] = applied
    record['restart'] = {'component': component, 'version': version, 'port': port,
                         'message': f'{component} {version} è stato selezionato: '
                                    'riavvia la dashboard per usarlo.'}
    path = marker_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    from serve.configuration import atomic_json
    atomic_json(path, record)
    return record['restart']


def restart_pending(root):
    """The restart the user is being offered, or None when nothing is pending."""
    entry = _read(root).get('restart')
    return entry if isinstance(entry, dict) and entry.get('component') else None


def clear_restart_pending(root):
    """The offer is spent once the restart happens (or the user dismisses it)."""
    record = _read(root)
    if 'restart' not in record:
        return False
    record.pop('restart', None)
    path = marker_path(root)
    if not record:
        path.unlink(missing_ok=True)
        return True
    from serve.configuration import atomic_json
    atomic_json(path, record)
    return True


def applied_versions(root):
    """Versions already selected here, so their notifications never return."""
    return dict(_read(root).get('applied') or {})


def restart_command(argv, port):
    """Rebuild the launch command of the running dashboard, for the same port only."""
    if not argv:
        raise ValueError('No running command to restart')
    script = next((arg for arg in argv if 'server.py' in str(arg)), None)
    if script is None:
        raise ValueError('The running process is not the dashboard')
    if '--port' in argv:
        index = argv.index('--port')
        if index + 1 >= len(argv) or int(argv[index + 1]) != int(port):
            raise ValueError('Restart is only offered for the port this dashboard serves')
    elif int(port) not in (8090, 8088):
        raise ValueError('Restart is only offered for a documented dashboard port')
    rest = [arg for arg in argv if arg is not script]
    return {'script': str(script), 'port': int(port), 'args': rest}
