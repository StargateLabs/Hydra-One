"""Fetch an official source archive as a read-only baseline for the mod manifest.

The archive is downloaded from the official repository, size-capped, and
extracted with the same safety rules as the update centre: no links, no
absolute or parent paths, no encrypted entries, bounded file count and size.
The destination is never overwritten.
"""
from __future__ import annotations
import hashlib
import io
import json
import re
import shutil
import stat
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

DEFAULT_MAX_BYTES = 256 * 1024 ** 2
MAX_FILES = 20000
MAX_FILE_BYTES = 64 * 1024 ** 2
MAX_EXTRACTED_BYTES = 512 * 1024 ** 2
_REPOSITORY = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
_TAG = re.compile(r'[A-Za-z0-9_.-]+')


def read_baseline_version(destination) -> str | None:
    try:
        record = json.loads((Path(destination) / 'BASELINE.json').read_text(encoding='utf-8'))
        return record.get('tag') if isinstance(record, dict) else None
    except (OSError, ValueError):
        return None


def _entry_name(entry) -> str:
    return entry.filename.replace('\\', '/')


def _check_entry(entry, name: str) -> None:
    if name.startswith('/') or ':' in name or '..' in Path(name).parts:
        raise ValueError('Unsafe baseline archive path')
    if stat.S_ISLNK(entry.external_attr >> 16):
        raise ValueError('Baseline archive links are not allowed')
    if entry.flag_bits & 1:
        raise ValueError('Encrypted baseline archives are not supported')


def fetch_official_source(repository: str, tag: str, destination, opener=None,
                          max_bytes: int = DEFAULT_MAX_BYTES, expected_sha256: str | None = None) -> dict:
    """Download `<repository>` at `<tag>` and extract it under `destination`."""
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ValueError('Invalid official repository')
    if not isinstance(tag, str) or not _TAG.fullmatch(tag):
        raise ValueError('Invalid official tag')
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Baseline destination already exists; refusing to overwrite it')
    source = f'https://api.github.com/repos/{repository}/zipball/{tag}'
    request = urllib.request.Request(source, headers={'User-Agent': 'Strata-ModBaseline'})
    open_ = opener or urllib.request.urlopen
    with open_(request, timeout=60) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Official archive exceeds the baseline size limit')
    archive_sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and archive_sha256 != str(expected_sha256).lower():
        raise ValueError('Downloaded baseline does not match the expected SHA-256')
    work = destination.with_name(destination.name + '.partial-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    try:
        rows = []
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                raise ValueError('Baseline archive exceeds the file-count limit')
            names = [_entry_name(entry) for entry in entries if not entry.is_dir()]
            prefix = None
            if names:
                head = names[0].split('/', 1)
                if len(head) != 2 or not all(name.startswith(head[0] + '/') for name in names):
                    raise ValueError('Baseline archive must contain a single top-level directory')
                prefix = head[0] + '/'
            total = 0
            for entry in entries:
                name = _entry_name(entry)
                _check_entry(entry, name)
                total += entry.file_size
                if entry.file_size > MAX_FILE_BYTES or total > MAX_EXTRACTED_BYTES:
                    raise ValueError('Baseline archive exceeds the extraction limits')
            for entry in entries:
                name = _entry_name(entry)
                relative = name[len(prefix):] if prefix and name.startswith(prefix) else name
                if not relative:
                    continue
                if '..' in Path(relative).parts or relative.startswith('/') or ':' in relative:
                    raise ValueError('Unsafe extracted baseline path')
                output = (work / relative).resolve()
                if not output.is_relative_to(work):
                    raise ValueError('Unsafe extracted baseline destination')
                if entry.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                written = 0
                with archive.open(entry) as source_stream, output.open('xb') as sink:
                    while block := source_stream.read(1024 * 1024):
                        written += len(block)
                        if written > entry.file_size:
                            raise ValueError('Extracted baseline file exceeds its declared size')
                        sink.write(block)
                        digest.update(block)
                if written != entry.file_size:
                    raise ValueError('Truncated baseline archive member')
                rows.append({'path': relative, 'bytes': written, 'sha256': digest.hexdigest()})
        record = {'repository': repository, 'tag': tag, 'source': source,
                  'archive_sha256': archive_sha256, 'file_count': len(rows),
                  'files': rows, 'extracted_at': time.time()}
        (work / 'BASELINE.json').write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
        work.rename(destination)
        return {'repository': repository, 'tag': tag, 'source': source,
                'archive_sha256': archive_sha256, 'files': len(rows), 'destination': str(destination)}
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
