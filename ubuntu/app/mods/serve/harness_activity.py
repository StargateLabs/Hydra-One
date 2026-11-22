"""Read native execution signals without changing sessions."""
import base64
import json
import sqlite3
import time
import urllib.request
from contextlib import closing


def activity(harness):
    if harness.child is None or harness.child.poll() is not None:
        return {'busy': False, 'activity_known': True}
    try:
        root = harness.root
        if harness.kind == 'opencode':
            auth = base64.b64encode(('opencode:' + harness.password).encode()).decode()
            request = urllib.request.Request(f'http://127.0.0.1:{harness.port}/api/session/active', headers={'Authorization': 'Basic ' + auth})
            with urllib.request.urlopen(request, timeout=1) as response:
                rows = json.load(response)['data']
            busy = bool(rows)
        elif harness.kind == 'dsh':
            busy = False
            for path in (root / 'data/dsh-home/storages/session_projcache/sessions').glob('*.json'):
                rows = json.loads(path.read_text(encoding='utf-8'))['record']['rows']
                boundary = rows.get('turnBoundary', {}).get('val', {})
                stats = rows.get('sessionStats', {}).get('val', {})
                busy |= boundary.get('openTurnStartSeq') is not None or stats.get('openStep') is not None or bool(stats.get('pendingCalls'))
        else:
            path = root / ('data/hermes-home/state.db' if harness.kind == 'hermes' else 'data/trueforge-home/db.sqlite')
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                if harness.kind == 'hermes':
                    busy = bool(db.execute('SELECT 1 FROM session_turn_leases WHERE expires_at > ? LIMIT 1', (time.time(),)).fetchone())
                else:
                    states = []
                    for row in db.execute('SELECT state FROM turn'):
                        value = json.loads(row[0])
                        if not isinstance(value, dict) or 'status' not in value:
                            raise ValueError('Unknown native turn state')
                        states.append(value['status'])
                    busy = any(state == 'running' for state in states)
        return {'busy': bool(busy), 'activity_known': True}
    except Exception:
        # An unavailable native signal is not proof that it is safe to kill an agent.
        return {'busy': True, 'activity_known': False}
