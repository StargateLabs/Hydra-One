"""Safe update entry point: check, prepare, validate — and activate only on request.

    python tools/aggiorna_sicuro.py                 # what can be updated, and what blocks it
    python tools/aggiorna_sicuro.py --prepare        # stage, prepare and validate the candidates
    python tools/aggiorna_sicuro.py --activate       # activate what has a current validated proof

Nothing runs unless the system is idle and the free RAM covers the check. Activation is a
separate step on purpose: it happens only against a proof this tool just verified.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from serve.safe_update import plan_update, READY, PREFLIGHT_FAILED

BASE = 'http://127.0.0.1:8090'


def call(path, body=None, timeout=30, method=None):
    data = json.dumps(body).encode() if body is not None else (b'{}' if method == 'POST' else None)
    request = urllib.request.Request(BASE + path, data=data,
                                     headers={'Content-Type': 'application/json'},
                                     method=method or ('POST' if body is not None else 'GET'))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read().decode()[:400])
        except ValueError:
            return {'error': {'message': f'HTTP {error.code}'}}


class Dashboard:
    """The running dashboard, read through its own API."""

    def __init__(self):
        self.health = call('/health', timeout=10)
        self.state = call('/updates', timeout=60)

    @property
    def engine(self):
        return self.health.get('loaded') and 'loading' or 'unloaded'

    @property
    def backend(self):
        return (self.state.get('components') and 'idle') or 'idle'

    @property
    def harnesses(self):
        class Harness:
            def __init__(self, status):
                self._status = status

            def status(self):
                return self._status

        result = {}
        for kind in ('opencode', 'dsh', 'trueforge', 'hermes', 'claude'):
            snapshot = call(f'/harness/{kind}/status', timeout=15)
            result[kind] = Harness({'status': snapshot.get('status'), 'busy': snapshot.get('busy')})
        return result

    def components(self):
        return self.state.get('components') or []

    def headroom_gib(self):
        import psutil
        return psutil.virtual_memory().available / 1024 ** 3


def report(plan):
    print()
    if plan.state == PREFLIGHT_FAILED:
        print('  AGGIORNAMENTO BLOCCATO')
        print(f'    motivo: {plan.reason}')
        return False
    print('  SISTEMA PRONTO PER GLI AGGIORNAMENTI')
    if plan.reclaim:
        print(f'    agenti da fermare prima (inattivi): {", ".join(plan.reclaim)}')
    print(f'    RAM libera sufficiente: si')
    if plan.components:
        print(f'    aggiornabili: {", ".join(plan.components)}')
    else:
        print('    aggiornabili: nessuno')
    for entry in plan.skipped:
        print(f'    saltato: {entry}')
    print()
    print('    attivazione automatica: MAI (richiede --activate con prova valida)')
    return True


def prepare():
    for step in ('stage', 'prepare'):
        result = call('/updates/' + step, timeout=900)
        job = result.get('download') or {}
        print(f'  {step:9} -> {job.get("state")}'
              + (f'  ({job.get("error")})' if job.get('error') else ''))
        if job.get('error'):
            return False
    result = call('/updates/validate-inference', timeout=300)
    print(f'  validate  -> {(result.get("download") or {}).get("state")}')
    for _ in range(80):
        time.sleep(3)
        job = call('/updates', timeout=30).get('download') or {}
        if job.get('state') not in ('validating', 'preparing'):
            break
    print(f'  esito     -> {job.get("state")}'
          + (f'  ({job.get("error")})' if job.get('error') else ''))
    state = call('/updates', timeout=30)
    print(f'  prova valida: {bool(state.get("strata_candidate_validation_current"))}')
    return bool(state.get('strata_candidate_validation_current'))


def activate():
    state = call('/updates', timeout=30)
    if not state.get('strata_candidate_validation_current'):
        print('  NESSUNA PROVA VALIDA: attivazione rifiutata.')
        return False
    job = (state.get('download') or {})
    print(f'  attivazione di {job.get("component")} {job.get("version")}...')
    result = call('/updates/activate', timeout=900)
    job = result.get('download') or {}
    print(f'  activate  -> {job.get("state")}'
          + (f'  ({job.get("error")})' if job.get('error') else ''))
    return not job.get('error')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='stage, prepare and validate')
    parser.add_argument('--activate', action='store_true', help='activate a candidate with a current proof')
    options = parser.parse_args()

    dashboard = Dashboard()
    if dashboard.health.get('error'):
        print('  La dashboard non risponde sulla 8090.')
        return 1

    plan = plan_update(dashboard, headroom_gib=dashboard.headroom_gib(),
                       components=dashboard.components())
    ready = report(plan)
    if not ready:
        return 1
    if options.prepare:
        print()
        if not prepare():
            return 1
    if options.activate:
        print()
        if not activate():
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
