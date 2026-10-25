"""Finite, explicit laboratory recovery. Historical quarantine stays intact.

The lab process must opt in through a private manifest. A ticket admits only
one native server launch for a frozen workload, under the existing mutex/Job.
Consumption occurs before spawn, so a crash cannot authorize an implicit retry.
"""
import hashlib
import json
import os
from pathlib import Path
import time

PROFILE = 'v8-recovery-qwen'
PROMPT = 'Complete this sequence with one number: 1, 2, 3,'
MODEL = 'local/Qwen3-0.6B-Q8_0'


def persist_module_evidence(row, modules, folder):
    # Identity may already belong to an append-only event: replace the mapping.
    identity = dict(row['process_identity'], loaded_DLL_map=modules)
    try:
        (Path(folder)/'loaded-modules.json').write_text(json.dumps(identity, indent=2), encoding='utf8')
    except OSError as exc:
        raise RuntimeError('DIAGNOSTIC_PERSISTENCE_FAILED before inference: '+str(exc)) from exc
    row['process_identity'] = identity
    from datetime import datetime, timezone
    import copy
    row.setdefault('events', []).append(dict(kind='native_module_map', at=datetime.now(timezone.utc).isoformat(), detail=copy.deepcopy(identity)))


def request_indices(samples):
    if type(samples) is not int or samples not in (1, 3):
        raise ValueError('RECOVERY_REQUEST_COUNT')
    return range(1, samples + 1)


def validate_body(body, grant):
    expected = dict(profile=PROFILE, model_id=MODEL, prompt=PROMPT,
                    max_tokens=8, samples=grant['samples'])
    if any(body.get(k) != v or type(body.get(k)) is not type(v) for k, v in expected.items()):
        raise ValueError('RECOVERY_FROZEN_WORKLOAD_MISMATCH')
    request_indices(body['samples'])
    prefix = grant.get('prompt_prefix', 'v16-')
    if prefix not in ('v16-', 'v17-') or not str(body.get('prompt_id', '')).startswith(prefix):
        raise ValueError('RECOVERY_PROMPT_ID')


def load_grant():
    if os.environ.get('HYDRA_LAB_MODE') != '1' or not os.environ.get('HYDRA_GPU_RECOVERY_MANIFEST'):
        raise ValueError('RECOVERY_EXPLICIT_SESSION_REQUIRED')
    path = Path(os.environ['HYDRA_GPU_RECOVERY_MANIFEST']).resolve()
    grant = json.loads(path.read_text(encoding='utf8'))
    if grant.get('state') != 'ARMED' or time.time() > grant.get('expires_at', 0):
        raise ValueError('RECOVERY_NOT_ARMED_OR_EXPIRED')
    if grant.get('samples') not in (1, 3):
        raise ValueError('RECOVERY_REQUEST_COUNT')
    if not isinstance(grant.get('ticket_id'), str) or not grant['ticket_id'].isalnum():
        raise ValueError('RECOVERY_TICKET_ID')
    probe = json.loads(Path(grant['probe']).read_text(encoding='utf8'))
    released = json.loads(Path(grant['probe']).with_name('released-lease.json').read_text(encoding='utf8'))
    if probe.get('status') != 'PASS' or not probe.get('child_cleanup_verified') or released.get('state') != 'RELEASED':
        raise ValueError('RECOVERY_PROBE_NOT_VERIFIED')
    if probe['child_result'].get('generation_requests') != 0 or not probe['child_result'].get('backend_freed'):
        raise ValueError('RECOVERY_PROBE_NOT_MODEL_FREE')
    for name, expected in grant['protected_markers'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError('RECOVERY_MARKER_CHANGED')
    grant['_path'] = str(path)
    return grant


def feature_available():
    try:
        g = load_grant()
        return not Path(g['_path']).with_name(g['ticket_id']+'.consumed.json').exists()
    except (ValueError, KeyError, OSError, TypeError):
        return False


def public_status():
    """No secrets or private paths; historical GPU profiles stay quarantined."""
    status = dict(profile=PROFILE, available=False, prompt=PROMPT, max_tokens=8,
                  samples=1, reason='GPU recovery is OFF or its finite ticket is unavailable')
    try:
        if not feature_available():
            return status
        import sqlite3
        db=Path(__file__).resolve().parents[1]/'data/hydra-benchmark-registry/benchmarks.sqlite'
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as connection:
            row=connection.execute('SELECT payload FROM feature_revisions ORDER BY version DESC LIMIT 1').fetchone()
        if not row or not json.loads(row[0])['features']['runtime.vulkan']['desired']:
            return status
        grant=load_grant()
        status.update(available=True,samples=grant['samples'],prompt_prefix=grant.get('prompt_prefix','v16-'),
                      reason='Finite experimental recovery; one native launch; no automatic retry')
    except (ValueError,KeyError,OSError,TypeError,sqlite3.Error):
        pass
    return status


def verified_gpu_evidence():
    """Describe persisted generations, never grant permission from a PASS alone."""
    import sqlite3
    db=Path(__file__).resolve().parents[1]/'data/hydra-benchmark-registry/benchmarks.sqlite'
    result=dict(run_ids=[],request_count=0,scope='Qwen3-0.6B-Q8_0; context 512; max 8 tokens; Vulkan 29/29; no performance promotion')
    if not db.is_file():
        return result
    try:
        with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as connection:
            rows=connection.execute("SELECT payload FROM runs WHERE json_extract(payload,'$.profile')=? AND json_extract(payload,'$.status')='PASS'",(PROFILE,)).fetchall()
        for payload, in rows:
            row=json.loads(payload)
            samples=row.get('samples',[])
            if row.get('backend')!='Vulkan' or row.get('actual_layers')!=29 or row.get('cleanup') is not True or not samples:
                continue
            if not isinstance(row.get('process_identity',{}).get('loaded_DLL_map'),list):
                continue
            if not all(s.get('output') and 0<s.get('tokens',0)<=8 and s.get('response',{}).get('tokens') for s in samples):
                continue
            result['run_ids'].append(row['run_id']);result['request_count']+=len(samples)
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):
        return dict(run_ids=[],request_count=0,scope='NOT_AVAILABLE')
    return result


def selected(body, cfg):
    grant = load_grant(); validate_body(body, grant)
    if not feature_available():
        raise ValueError('RECOVERY_TICKET_ALREADY_CONSUMED')
    if cfg != grant['runtime_spec']:
        raise ValueError('RECOVERY_RUNTIME_MANIFEST_MISMATCH')
    from serve.hydra_fastpath import spec
    value = spec('v8-qwen-full', {'qwen': cfg}, True)
    value.update(recovery=True, context=512, flags=['-fa', 'off', '--cache-ram', '0', '--ctx-checkpoints', '0'], cache=False,
                 deadline_s=90, app_paths=False, no_warmup=True,
                 selection_reason='v16 controlled recovery; not a promoted performance profile')
    return value


def allow_spawn(request, argv):
    """Called only under the existing exclusive coordinator, before child creation."""
    if request.get('profile') != PROFILE or 'runtime.vulkan' not in request.get('feature_required', []):
        return False
    grant = load_grant(); spec = grant['runtime_spec']; binary = Path(spec['runtime'])/'llama-server.exe'
    if Path(str(argv[0])).resolve() != binary.resolve():
        return False
    for name, expected in spec['files'].items():
        with (Path(spec['runtime'])/name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('RECOVERY_RUNTIME_HASH_CHANGED')
    if len(argv) == 2 and argv[1] == '--list-devices':
        return feature_available()
    checks = {'-m': spec['model'], '-ngl': '29', '--device': 'Vulkan0', '-c': '512',
              '--parallel': '1', '-t': '2', '-tb': '2', '-fa': 'off', '--host': '127.0.0.1',
              '--cache-ram': '0', '--ctx-checkpoints': '0'}
    for flag, value in checks.items():
        if list(argv).count(flag) != 1 or argv[list(argv).index(flag)+1] != value:
            raise ValueError('RECOVERY_NATIVE_ARGUMENT_MISMATCH: '+flag)
    with Path(spec['model']).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != spec['model_hash']:
            raise ValueError('RECOVERY_MODEL_HASH_CHANGED')
    consumed = Path(grant['_path']).with_name(grant['ticket_id']+'.consumed.json')
    with consumed.open('x', encoding='utf8') as stream:
        json.dump(dict(run_id=request['run_id'], at=time.time(), argv=argv,
                       samples=grant['samples'], max_tokens=8), stream, indent=2)
    return True
