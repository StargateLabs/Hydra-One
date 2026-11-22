"""Read-only, hash-verified comparison between this project and an official baseline.

The manifest is the replacement for `git diff` in a project without history:
it records which editable files the user changed, added or removed, with the
raw SHA-256 of both sides and a bounded unified diff for text files.  Nothing
here writes to a source tree; the only output is the manifest path the caller
chooses.
"""
from __future__ import annotations
import difflib
import hashlib
import json
import time
import uuid
from pathlib import Path
from serve.customization_backup import iter_editable_files

SCHEMA_VERSION = 1
DIFF_LIMIT = 64 * 1024
DIFF_BUDGET = 8 * 1024 ** 2
MAX_DIFF_INPUT_BYTES = 4 * 1024 ** 2
BINARY_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.ico', '.ttf', '.woff', '.woff2', '.zip'}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_meta(path: Path) -> dict:
    return {'bytes': path.stat().st_size, 'sha256': file_sha256(path)}


def is_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    with path.open('rb') as source:
        return b'\0' in source.read(8192)


def bounded_diff(baseline_path: Path, live_path: Path, relative: str) -> tuple[str, bool]:
    old = baseline_path.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
    new = live_path.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
    text = ''.join(difflib.unified_diff(old, new, fromfile='baseline/' + relative, tofile='live/' + relative))
    return (text[:DIFF_LIMIT], True) if len(text) > DIFF_LIMIT else (text, False)


def compare_trees(live_root, baseline_root, *, include_diffs=True) -> list[dict]:
    """Every editable path in either tree, with its status and hashes."""
    live_root = Path(live_root).resolve()
    baseline_root = Path(baseline_root).resolve()
    live = {relative: path for path, relative in iter_editable_files(live_root)}
    baseline = {relative: path for path, relative in iter_editable_files(baseline_root)}
    rows = []
    for relative in sorted(set(live) | set(baseline)):
        live_path, baseline_path = live.get(relative), baseline.get(relative)
        live_meta = file_meta(live_path) if live_path else None
        baseline_meta = file_meta(baseline_path) if baseline_path else None
        status = ('deleted' if live_path is None else
                  'added' if baseline_path is None else
                  'unchanged' if live_meta['sha256'] == baseline_meta['sha256'] else 'modified')
        row = {'path': relative, 'status': status, 'live': live_meta, 'baseline': baseline_meta,
               'binary': False, 'diff': None, 'diff_truncated': False}
        if include_diffs:
            row['binary'] = ((live_path is not None and is_binary(live_path)) or
                             (baseline_path is not None and is_binary(baseline_path)))
        else:
            row['binary'] = any(path is not None and path.suffix.lower() in BINARY_SUFFIXES
                                for path in (live_path, baseline_path))
        if status == 'modified' and include_diffs and not row['binary']:
            largest = max(live_meta['bytes'], baseline_meta['bytes'])
            if largest > MAX_DIFF_INPUT_BYTES:
                row['diff_truncated'] = True
            else:
                row['diff'], row['diff_truncated'] = bounded_diff(baseline_path, live_path, relative)
        rows.append(row)
    return rows


def build_manifest(live_root, baseline_root, *, baseline_version=None, baseline_archive_sha256=None,
                   include_diffs=True, diff_budget: int = DIFF_BUDGET) -> dict:
    files = compare_trees(live_root, baseline_root, include_diffs=include_diffs)
    kept = 0
    for row in files:
        if row['diff'] is None:
            continue
        if kept + len(row['diff']) > diff_budget:
            row['diff'] = None
            row['diff_truncated'] = True
        else:
            kept += len(row['diff'])
    summary = {'total': len(files), 'unchanged': 0, 'modified': 0, 'added': 0, 'deleted': 0,
               'binary': 0, 'diff_bytes': 0}
    for row in files:
        summary[row['status']] += 1
        summary['binary'] += int(bool(row['binary']))
        summary['diff_bytes'] += len(row['diff'] or '')
    return {'schema_version': SCHEMA_VERSION, 'generated_at': time.time(),
            'live_root': str(Path(live_root).resolve()), 'baseline_root': str(Path(baseline_root).resolve()),
            'baseline_version': baseline_version, 'baseline_archive_sha256': baseline_archive_sha256,
            'files': files, 'summary': summary}


def write_manifest(manifest: dict, path) -> Path:
    """Write the manifest atomically; the source trees are never touched."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
