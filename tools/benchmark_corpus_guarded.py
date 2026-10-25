"""Run the archived corpus harness with immediate failure; never retry a GPU fault."""
import importlib.util
import json
from pathlib import Path
import sys
from benchmark_guard import require_run_result

ROOT = Path(__file__).resolve().parents[1]

def main():
    path = ROOT/'bench/results/2026-09-29-rtx3090-epyc-milan/data/strata-bench.py'
    spec = importlib.util.spec_from_file_location('corpus_reference', path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    original = harness.run_once
    def guarded(*args, **kwargs):
        result = original(*args, **kwargs)
        try:
            return require_run_result(result)
        except RuntimeError:
            out = ROOT/'output/verification'
            out.mkdir(parents=True, exist_ok=True)
            (out/'corpus-last-failure.json').write_text(json.dumps(result[0], indent=2), encoding='utf-8')
            raise
    harness.run_once = guarded
    harness.main()

if __name__ == '__main__':
    main()
