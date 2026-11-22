"""CLI: write a readable conflict report for a mod-preserving update plan."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.mod_apply import CODE_PREFIXES, plan_apply
from serve.mod_report import build_report, render_markdown


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Report every conflict between the user edit and a new official baseline; never writes live files.')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--live', required=True)
    parser.add_argument('--old-baseline', required=True)
    parser.add_argument('--new-baseline', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--scope', choices=('code', 'all'), default='code')
    args = parser.parse_args(argv)
    live, old, new = Path(args.live).resolve(), Path(args.old_baseline).resolve(), Path(args.new_baseline).resolve()
    if not live.is_dir() or not old.is_dir() or not new.is_dir():
        print('--live, --old-baseline and --new-baseline must be existing directories', file=sys.stderr)
        return 2
    output = Path(args.out_dir).resolve()
    if output.is_relative_to(live) and not output.is_relative_to(live / 'output'):
        print('refusing to write the report inside the live tree', file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
            raise ValueError('not a manifest')
    except (OSError, ValueError) as error:
        print(f'cannot read manifest: {error}', file=sys.stderr)
        return 2
    plan = plan_apply(manifest, live, old, new, prefixes=None if args.scope == 'all' else CODE_PREFIXES)
    report = build_report(plan, live, old, new)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'conflicts.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    markdown = render_markdown(report)
    (output / 'conflicts.md').write_text(markdown, encoding='utf-8')
    template = {row['path']: None for row in report['conflicts']}
    (output / 'resolutions-template.json').write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"conflicts={report['summary']['conflicts']} warnings={report['summary']['warnings']} "
          f"stale={report['summary']['stale']} report={output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
