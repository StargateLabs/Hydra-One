"""Atomic configuration persistence and strict integer budget validation."""
import json
import math
import os
import tempfile
import time
from pathlib import Path


def whole_number(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a whole number")
    try:
        n = int(value)
        if isinstance(value, float) and (not math.isfinite(value) or value != n):
            raise ValueError()
        if isinstance(value, str) and str(n) != value.strip():
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} must be a whole number, not {value!r}") from None
    if not low <= n <= high:
        raise ValueError(f"{name} must be between {low} and {high}, not {n}")
    return n


def atomic_json(path, data):
    target = Path(path)
    raw = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.name + ".", suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        # Windows readers/antivirus can temporarily deny replacement. Keep the
        # previous complete file and retry briefly; never fall back to truncation.
        for attempt in range(10):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 9:raise
                time.sleep(.05*(attempt+1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
