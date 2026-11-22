#!/usr/bin/env python3
"""Assemble the Ubuntu source snapshot and its unchanged public catalogue."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

here = Path(__file__).resolve().parent
repository = here.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('destination', type=Path, help='new directory for the assembled app')
args = parser.parse_args()
dest = args.destination.expanduser().resolve()
if dest.exists():
    parser.error('destination already exists')
checks = json.loads((here / 'catalog-sha256.json').read_text())
for name, expected in checks.items():
    source = repository / 'serve' / 'web' / name
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        parser.error(f'missing or changed public catalogue file: {name}')
shutil.copytree(here / 'app', dest)
for name in checks:
    shutil.copy2(repository / 'serve' / 'web' / name, dest / 'serve' / 'web' / name)
print(f'Ubuntu app sources assembled at {dest}')
