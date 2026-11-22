"""CLI: plan (dry-run) or materialise a mod-preserving update candidate."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.mod_apply import CODE_PREFIXES, materialize, plan_apply


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Decide how the user edits combine with a new official baseline; never writes live files.')
    parser.add_argument('--manifest', required=True, help='manifest JSON from tools/mod_manifest.py')
    parser.add_argument('--live', required=True, help='live project root (read-only)')
    parser.add_argument('--old-baseline', required=True, help='baseline the manifest was built against')
    parser.add_argument('--new-baseline', required=True, help='official baseline to update to')
    parser.add_argument('--out', required=True, help='candidate directory to materialise')
    parser.add_argument('--scope', choices=('code', 'all'), default='code', help='code/config prefixes, or every editable path')
    parser.add_argument('--resolutions', default=None, help='JSON mapping conflicted paths to keep_live|take_new')
    parser.add_argument('--materialize', action='store_true', help='write the candidate when the plan is ready')
    args = parser.parse_args(argv)
    live, old, new = Path(args.live).resolve(), Path(args.old_baseline).resolve(), Path(args.new_baseline).resolve()
    if not live.is_dir() or not old.is_dir() or not new.is_dir():
        print('--live, --old-baseline and --new-baseline must be existing directories', file=sys.stderr)
        return 2
    output = Path(args.out).resolve()
    if output.is_relative_to(live) and not output.is_relative_to(live / 'output'):
        print('refusing to write the candidate inside the live tree', file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
            raise ValueError('not a manifest')
    except (OSError, ValueError) as error:
        print(f'cannot read manifest: {error}', file=sys.stderr)
        return 2
    resolutions = None
    if args.resolutions:
        try:
            resolutions = json.loads(Path(args.resolutions).read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            print(f'cannot read resolutions: {error}', file=sys.stderr)
            return 2
    try:
        plan = plan_apply(manifest, live, old, new, prefixes=None if args.scope == 'all' else CODE_PREFIXES,
                          resolutions=resolutions)
    except ValueError as error:
        print(f'invalid resolutions: {error}', file=sys.stderr)
        return 2
    counts = plan['counts']
    print(f"ready={plan['ready']} scope={args.scope} take_new={counts['take_new']} take_live={counts['take_live']} "
          f"keep_absent={counts['keep_absent']} conflicts={counts['conflict']} stale={len(plan['stale'])} "
          f"warnings={len(plan.get('warnings', []))}")
    if not plan['ready']:
        for conflict in plan['conflicts'][:20]:
            print(f"  conflict {conflict['path']} ({conflict['kind']})")
        for stale in plan['stale'][:20]:
            print(f"  stale {stale['path']} ({stale['reason']})")
        return 3
    if args.materialize:
        result = materialize(plan, live, new, output)
        print(f"candidate={result['destination']} overlaid={result['files']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
