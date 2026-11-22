"""Readable conflict report for a mod-preserving update plan.

The report shows, per conflicted path, the upstream change and the user's
change side by side.  It never merges and never writes to a source tree;
its only output is the caller's report directory.
"""
from __future__ import annotations
import difflib
import time
from pathlib import Path
from serve.mod_manifest import is_binary

DIFF_LIMIT = 8192


def _diff(left: Path, right: Path, left_label: str, right_label: str, relative: str, limit: int) -> str | None:
    if not left.is_file() or not right.is_file():
        return None
    try:
        if is_binary(left) or is_binary(right):
            return None
        old = left.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
        new = right.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
    except OSError:
        return None
    text = ''.join(difflib.unified_diff(old, new, fromfile=left_label + '/' + relative, tofile=right_label + '/' + relative))
    return text[:limit] + ('\n[diff truncated]' if len(text) > limit else '')


def build_report(plan: dict, live_root, old_baseline_root, new_baseline_root, *, diff_limit: int = DIFF_LIMIT) -> dict:
    live_root, old_root, new_root = Path(live_root).resolve(), Path(old_baseline_root).resolve(), Path(new_baseline_root).resolve()
    conflicts = []
    for row in plan.get('conflicts', []):
        path = row['path']
        conflicts.append({'path': path, 'kind': row.get('kind'), 'live': row.get('live'), 'old': row.get('old'),
                          'new': row.get('new'),
                          'upstream_diff': _diff(old_root / path, new_root / path, 'old', 'new', path, diff_limit),
                          'user_diff': _diff(old_root / path, live_root / path, 'old', 'live', path, diff_limit)})
    return {'schema_version': 1, 'generated_at': time.time(),
            'summary': {'conflicts': len(conflicts), 'warnings': len(plan.get('warnings', [])),
                        'stale': len(plan.get('stale', []))},
            'conflicts': conflicts, 'warnings': plan.get('warnings', []), 'stale': plan.get('stale', [])}


def render_markdown(report: dict) -> str:
    lines = ['# Conflict report', '',
             f"- conflicts: {report['summary']['conflicts']}",
             f"- warnings: {report['summary']['warnings']}",
             f"- stale: {report['summary']['stale']}", '']
    for row in report['conflicts']:
        lines += [f"## {row['path']}", '', f"- kind: `{row['kind']}`"]
        for label, key in (('Upstream (old -> new)', 'upstream_diff'), ('User (old -> live)', 'user_diff')):
            lines += ['', f"### {label}", '']
            diff = row.get(key)
            if diff:
                lines += ['```diff', diff.rstrip(), '```']
            else:
                lines += ['_no text diff (missing side or binary)_']
        lines.append('')
    return '\n'.join(lines)
