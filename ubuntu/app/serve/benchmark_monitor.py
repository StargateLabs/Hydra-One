"""Read a local benchmark snapshot; stale producers are never shown as live."""
import json
import time
from pathlib import Path

SNAPSHOT = Path(__file__).resolve().parents[1]/'data/benchmark-live.json'

def snapshot(path=SNAPSHOT, now=None):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        age = (time.time() if now is None else now) - float(data['updated_at'])
        if not isinstance(data.get('metrics'), dict) or age < -5:
            return None
        data['metrics'].pop('benchmark', None)
        label=data.get('label','')
        import re
        if isinstance(label,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,180}',label):
            from serve.startup_timing import snapshot as startup_snapshot
            timing=startup_snapshot(Path(__file__).resolve().parents[1]/'output/verification'/f'{label}-engine.log')
            if timing:data['metrics'].setdefault('engine',{})['startup']=timing
        data['active'] = bool(data.get('active')) and age <= 8
        data['stale'] = age > 8
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


def competing_benchmark(local_port, path=SNAPSHOT, now=None):
    """Only a fresh producer on another local server reserves this project's GPU."""
    data = snapshot(path, now)
    if not data or not data['active']:
        return None
    producer = data.get('source_port')
    if type(local_port) is not int or type(producer) is not int:
        return None
    if not 1 <= producer <= 65535 or producer == local_port:
        return None
    return str(data.get('label') or 'test isolato')[:120]
