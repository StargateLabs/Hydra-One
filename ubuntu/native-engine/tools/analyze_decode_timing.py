"""Inspect engine timing logs; estimates are budgets, not benchmark results."""
import argparse
import json
from pathlib import Path
import re
import statistics

NUMBER = r'(\d+(?:\.\d+)?)'
PATTERN = re.compile(
    r'strata decode timing: ' + NUMBER + r' windows, avg T ' + NUMBER
    + r', ' + NUMBER + r' tokens/window, ' + NUMBER + r' ms/window = verify '
    + NUMBER + r' \(GPU-reach wait ' + NUMBER + r' \+ per-layer host ' + NUMBER)


def analyze(path, target=100.0):
    rows = []
    for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines():
        match = PATTERN.search(line)
        if not match:
            continue
        windows, draft, tokens, total, verify, wait, host = map(float, match.groups())
        if tokens <= 0 or total <= 0:
            continue
        budget = tokens * 1000 / target
        rows.append(dict(windows=int(windows), average_draft=draft,
                         tokens_per_window=tokens, window_ms=total,
                         verify_ms=verify, gpu_reach_wait_ms=wait, host_ms=host,
                         target_window_ms=budget,
                         required_window_reduction_percent=max(0, 100 * (1-budget/total))))
    if not rows:
        raise ValueError('No valid decode timing records in this log')
    return dict(source=str(Path(path).resolve()), target_decode_tok_s=target,
                records=len(rows), medians={key: statistics.median(row[key] for row in rows)
                for key in rows[0] if key != 'windows'},
                limitations='Rounded engine diagnostics; all logged requests including warmup. '
                'GPU-reach wait includes synchronization and is not isolated kernel time. '
                'Target budget assumes unchanged tokens per window and does not predict a gain.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--target', type=float, default=100)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.target < float('inf'):
        parser.error('Target must be finite and positive')
    report = analyze(args.log, args.target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
