"""CLI: write a read-only manifest of this project's edits against a baseline."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from serve.mod_manifest import build_manifest, write_manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Compare editable files against an official baseline (read-only).')
    parser.add_argument('--live', required=True, help='project root to inspect')
    parser.add_argument('--baseline', required=True, help='official baseline root')
    parser.add_argument('--out', required=True, help='manifest JSON to write')
    parser.add_argument('--version', default=None, help='baseline version/tag, recorded in the manifest')
    parser.add_argument('--archive-sha256', default=None, help='official archive SHA-256, recorded in the manifest')
    parser.add_argument('--no-diffs', action='store_true', help='hashes only, never read text contents')
    args = parser.parse_args(argv)
    live, baseline = Path(args.live).resolve(), Path(args.baseline).resolve()
    if not live.is_dir() or not baseline.is_dir():
        print('both --live and --baseline must be existing directories', file=sys.stderr)
        return 2
    recorded = {}
    try:
        saved = json.loads((baseline / 'BASELINE.json').read_text(encoding='utf-8'))
        recorded = saved if isinstance(saved, dict) else {}
    except (OSError, ValueError):
        recorded = {}
    recorded_version, recorded_sha256 = recorded.get('tag'), recorded.get('archive_sha256')
    if args.version and recorded_version and args.version != recorded_version:
        print(f'baseline version mismatch: {args.version} != {recorded_version}', file=sys.stderr)
        return 2
    if args.archive_sha256 and recorded_sha256 and args.archive_sha256.lower() != str(recorded_sha256).lower():
        print('baseline archive SHA-256 mismatch', file=sys.stderr)
        return 2
    output = Path(args.out).resolve()
    if output.is_relative_to(live) and not output.is_relative_to(live / 'output'):
        print('refusing to write the manifest inside the live tree', file=sys.stderr)
        return 2
    version = args.version or recorded_version
    archive_sha256 = args.archive_sha256 or recorded_sha256
    manifest = build_manifest(live, baseline, baseline_version=version,
                              baseline_archive_sha256=archive_sha256,
                              include_diffs=not args.no_diffs)
    output = write_manifest(manifest, output)
    summary = manifest['summary']
    print(f"baseline={version or manifest['baseline_root']} archive_sha256={archive_sha256 or 'not-recorded'}")
    print(f"manifest={output} total={summary['total']} modified={summary['modified']} "
          f"added={summary['added']} deleted={summary['deleted']} unchanged={summary['unchanged']} "
          f"binary={summary['binary']} diff_bytes={summary['diff_bytes']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
