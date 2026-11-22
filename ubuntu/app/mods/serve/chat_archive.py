"""Durable copy of the web app's chat archive.

The browser keeps the archive in localStorage so the page works offline, but that copy
disappears with the browser profile, a private window or a full disk. This module keeps a
second copy under the project's data folder so no conversation is ever lost.

The browser copy stays authoritative for what it already has; this copy is only read back
when the browser has nothing, or to restore a conversation the user recalls.
"""
import json
from pathlib import Path

ARCHIVE_NAME = 'chat-archive.json'
ARCHIVE_LIMIT = 20 * 1024 ** 2


def archive_path(root):
    path = Path(root) / ARCHIVE_NAME
    if path.is_symlink():
        raise ValueError('Chat archive path must not be a link')
    return path


def read_archive(root):
    """The stored archive, or an empty list when there is nothing usable to read."""
    try:
        path = archive_path(root)
    except ValueError:
        return []
    try:
        if not path.is_file():
            return []
        rows = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows
            if isinstance(row, dict) and isinstance(row.get('id'), str)
            and isinstance(row.get('messages'), list)]


def save_archive(root, rows):
    """Persist the archive atomically; a rejected write never damages the stored copy."""
    if not isinstance(rows, list):
        raise ValueError('Chat archive must be a list')
    path = archive_path(root)
    raw = json.dumps(rows, ensure_ascii=False, allow_nan=False)
    if len(raw.encode('utf-8')) > ARCHIVE_LIMIT:
        raise ValueError('Chat archive exceeds ' + str(ARCHIVE_LIMIT // 1024 ** 2) + ' MiB')
    path.parent.mkdir(parents=True, exist_ok=True)
    from serve.configuration import atomic_json
    atomic_json(path, rows)
    return len(rows)
