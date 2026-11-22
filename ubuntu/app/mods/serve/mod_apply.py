"""Three-way apply planning for mod-preserving updates.

`plan_apply` decides per path whether the user's file, the new upstream file,
or neither wins.  Ambiguity is a conflict, never a guess.  `materialize`
writes the new baseline plus the user's wins into an isolated candidate; it
never touches the live tree.
"""
from __future__ import annotations
import json
import re
import shutil
import time
from pathlib import Path
from serve.customization_backup import iter_editable_files
from serve.mod_manifest import file_sha256

CODE_PREFIXES = ('serve/', 'src/', 'include/', 'tools/', 'tests/', 'bench/', 'docs/', 'HYDRA/', 'cmake/', '.github/')
NON_CODE_PREFIXES = ('docs/', 'bench/', '.github/')
NON_CODE_ROOT = re.compile(r'(README|AGENTS|SECURITY|CONTRIBUTING|LICENSE|CHANGELOG|CODE_OF_CONDUCT)(\..*)?$', re.I)


def is_code(path: str) -> bool:
    if '/' in path:
        return not path.startswith(NON_CODE_PREFIXES)
    return not NON_CODE_ROOT.fullmatch(path)


def _hash(path) -> str | None:
    path = Path(path)
    return file_sha256(path) if path.is_file() and not path.is_symlink() else None


def _in_scope(path: str, prefixes) -> bool:
    if prefixes is None:
        return True
    return '/' not in path or any(path.startswith(prefix) for prefix in prefixes)


def _decide(live, old, new):
    if live == old:
        return ('take_new', 'upstream') if new is not None else ('keep_absent', 'upstream_removed')
    if old == new:
        return ('take_live', 'user') if live is not None else ('keep_absent', 'user_deleted')
    if new is None:
        return ('conflict', 'modified_upstream_removed') if live is not None else ('keep_absent', 'user_deleted')
    if live is None:
        return ('conflict', 'user_deleted_upstream_changed')
    if live == new:
        return ('take_new', 'same_result')
    if old is None:
        return ('conflict', 'added_both')
    return ('conflict', 'both_changed')


def plan_apply(manifest: dict, live_root, old_baseline_root, new_baseline_root, *, prefixes=CODE_PREFIXES,
               resolutions=None) -> dict:
    """Return explicit actions and block on stale inputs or any ambiguity.

    `resolutions` maps a conflicted path to the operator's explicit choice:
    `keep_live` (preserve the user's file) or `take_new` (accept upstream).
    """
    resolutions = {} if resolutions is None else resolutions
    if not isinstance(resolutions, dict):
        raise ValueError('Resolutions must be a mapping of path to keep_live|take_new')
    if any(value not in ('keep_live', 'take_new') for value in resolutions.values()):
        raise ValueError('Invalid resolution; use keep_live or take_new')
    live_root, old_root, new_root = Path(live_root).resolve(), Path(old_baseline_root).resolve(), Path(new_baseline_root).resolve()
    known = {row['path']: row for row in manifest.get('files', []) if _in_scope(row['path'], prefixes)}
    new_paths = {relative for _, relative in iter_editable_files(new_root) if _in_scope(relative, prefixes)}
    stale, conflicts, actions, warnings = [], [], [], []
    for path in sorted(set(known) | new_paths):
        live, old, new = _hash(live_root / path), _hash(old_root / path), _hash(new_root / path)
        row = known.get(path)
        if row is not None:
            expected_live = row['live']['sha256'] if row.get('live') else None
            expected_old = row['baseline']['sha256'] if row.get('baseline') else None
            if live != expected_live:
                stale.append({'path': path, 'reason': 'live_changed'})
            if old != expected_old:
                stale.append({'path': path, 'reason': 'old_baseline_changed'})
        action, reason = _decide(live, old, new)
        explicit = path in resolutions
        if action == 'conflict' and explicit:
            choice = resolutions[path]
            action = ('take_live' if live is not None else 'keep_absent') if choice == 'keep_live' else \
                     ('take_new' if new is not None else 'keep_absent')
            reason = 'resolution_' + choice
        elif action == 'conflict' and not is_code(path):
            resolved = 'keep_absent' if reason == 'user_deleted_upstream_changed' or live is None else 'take_live'
            warnings.append({'path': path, 'kind': reason, 'resolution': resolved})
            action, reason = resolved, 'non_code_user_kept' if resolved == 'take_live' else 'non_code_user_deleted'
        actions.append({'path': path, 'action': action, 'reason': reason, 'live': live, 'old': old, 'new': new,
                        'resolved': explicit})
        if action == 'conflict':
            conflicts.append({'path': path, 'kind': reason, 'live': live, 'old': old, 'new': new})
    counts = {name: sum(1 for row in actions if row['action'] == name)
              for name in ('take_new', 'take_live', 'keep_absent', 'remove', 'conflict')}
    return {'schema_version': 1, 'ready': not stale and not conflicts, 'stale': stale,
            'conflicts': conflicts, 'warnings': warnings, 'actions': actions, 'counts': counts}


def materialize(plan: dict, live_root, new_baseline_root, destination) -> dict:
    """Copy the new baseline and overlay only the user's wins; live stays read-only."""
    if not plan.get('ready'):
        raise ValueError('The apply plan is stale or has conflicts')
    live_root = Path(live_root).resolve()
    new_root = Path(new_baseline_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Candidate destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(new_root, destination, ignore=shutil.ignore_patterns('BASELINE.json'))
    applied = 0
    for row in plan.get('actions', []):
        path = row['path']
        target = (destination / path).resolve()
        if not target.is_relative_to(destination):
            raise ValueError('Unsafe candidate path: ' + path)
        if row['action'] == 'take_live':
            source = (live_root / path).resolve()
            if not source.is_relative_to(live_root) or not source.is_file():
                raise ValueError('Live file disappeared: ' + path)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            applied += 1
        elif row['action'] == 'remove' and target.is_file():
            target.unlink()
    report = {'schema_version': 1, 'created_at': time.time(), 'destination': str(destination),
              'applied': applied, 'counts': plan.get('counts'), 'conflicts': plan.get('conflicts'),
              'stale': plan.get('stale')}
    (destination / 'APPLY-REPORT.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return {'destination': str(destination), 'files': applied, 'report': report}
