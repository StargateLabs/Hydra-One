"""Reversible, version guarded VoiceStudio 0.5.6 private-runtime telemetry repair.

No executable/package patch, model load, process restart, utilization invention,
or engine selection. Restore with --rollback before changing app versions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

ORIGINAL_SHA256 = '6a1b1c5e8cf558eb12a17d1069f4e3e41a2412041b18bd7e42209c1b1f24a494'
ANCHOR = '    gpu_utilization = None\n    nvidia_stats = _nvidia_live_stats() if _is_cuda else None\n'
ADDITION = '''    # Strata repair: native GPU engines run outside PyTorch's allocator.
    # Active means resident live GPU engine, matching the existing VRAM criterion;
    # it does not invent utilization or memory statistics for Vulkan.
    try:
        from services import tts_backend
        instances = list(tts_backend._ENGINE_INSTANCES.values())
        if tts_backend._active_instance is not None:
            instances.append(tts_backend._active_instance)
        for instance in instances:
            if (getattr(instance, "_provider", None) == "vulkan"
                    and getattr(instance, "_device", None) == "vulkan"
                    and instance.execution_evidence_loaded()):
                gpu_active = True
                break
    except Exception:
        logger.debug("Native GPU activity probe unavailable", exc_info=True)

'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--installed-source', action='store_true', help='Repair the source actually launched by Electron, under resources/backend')
    args = parser.parse_args()
    if args.apply == args.rollback: parser.error('Choose --apply or --rollback')
    target = Path(os.environ['APPDATA'])/'VoiceStudio/runtime/project/backend/api/routers/system.py'
    if args.installed_source:
        target = Path(os.environ['LOCALAPPDATA'])/'Programs/VoiceStudio/resources/backend/api/routers/system.py'
    backup = target.with_name('system.py.strata-vulkan-original')
    raw = target.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    original = raw.decode('utf-8').replace('\r\n', '\n')
    if args.rollback:
        if not backup.is_file(): raise RuntimeError('Original backup missing')
        saved = backup.read_bytes()
        if hashlib.sha256(saved).hexdigest() != ORIGINAL_SHA256: raise RuntimeError('Backup hash mismatch')
        expected = saved.decode('utf-8').replace('\r\n', '\n').replace(ANCHOR, ADDITION+ANCHOR).replace('\n', newline).encode('utf-8')
        if raw != expected: raise RuntimeError('Runtime changed since repair; rollback refused')
        target.write_bytes(saved)
    else:
        if ADDITION in original:
            print('Repair already applied; restart only when app is idle.'); return
        if hashlib.sha256(raw).hexdigest() != ORIGINAL_SHA256: raise RuntimeError('Different app source version; repair refused')
        if original.count(ANCHOR) != 1: raise RuntimeError('Telemetry anchor mismatch')
        repaired = original.replace(ANCHOR, ADDITION+ANCHOR)
        compile(repaired, str(target), 'exec')
        if backup.exists() and backup.read_bytes() != raw: raise RuntimeError('Backup differs; repair refused')
        backup.write_bytes(raw)
        target.write_bytes(repaired.replace('\n', newline).encode('utf-8'))
    evidence = {'target': str(target), 'backup': str(backup), 'original_sha256': ORIGINAL_SHA256,
                'result_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'action': 'rollback' if args.rollback else 'apply', 'restart_required': True,
                'utilization_preserved': 'unknown remains null'}
    output=Path(__file__).resolve().parents[1]/'output/voicestudio/vulkan-telemetry-repair.json'
    output.write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2))

if __name__ == '__main__': main()
