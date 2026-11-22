"""Verify profile-learning applicability offline; never overwrite the active profile."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from make_profile import read_profile

ROOT = Path(__file__).resolve().parents[1]

def main():
    config_path = ROOT/'strata-iq3_xxs.json'
    config_bytes = config_path.read_bytes()
    config = json.loads(config_bytes)
    args = config['args']
    profile_path = Path(args[args.index('--expert-profile')+1])
    original = profile_path.read_bytes()
    ranked = read_profile(profile_path)
    if len(ranked) != 24576 or len(set(ranked)) != 24576:
        raise ValueError('Expected a complete unique profile for this offline demonstration')
    target = ranked[-1]
    with tempfile.TemporaryDirectory(dir=ROOT/'output/verification') as folder:
        folder = Path(folder)
        trace = folder/'synthetic-routing.bin'
        trace.write_bytes(struct.pack('<iii f',target[0],1,target[1],1.0)*3)
        outputs = {}
        for mode in ('base-first','trace-first'):
            destination = folder/f'{mode}.bin'
            command = [sys.executable,str(ROOT/'tools/make_profile.py'),str(trace),'--out',str(destination)]
            command += ['--base',str(profile_path)] if mode == 'base-first' else ['--no-base']
            subprocess.run(command,cwd=ROOT,capture_output=True,text=True,check=True)
            ordering = read_profile(destination)
            outputs[mode] = dict(target_rank=ordering.index(target),first_pair=ordering[0],
                pair_count=len(ordering),original_order_unchanged=ordering == ranked)
    if profile_path.read_bytes() != original or config_path.read_bytes() != config_bytes:
        raise RuntimeError('Operational input changed')
    result = dict(kind='Offline synthetic routing demonstration; no inference or speed claim',
        model=config['model_name'],config_sha256=hashlib.sha256(config_bytes).hexdigest(),
        profile_sha256=hashlib.sha256(original).hexdigest(),profile_pairs=len(ranked),
        profile_save_configured='--expert-profile-save' in args,
        lookahead_configured=config.get('env',{}).get('STRATA_LOOKAHEAD'),
        demonstration=outputs,target=list(target),operational_inputs_unchanged=True,
        conclusion='A full base-first profile prevents appended trace frequencies from changing the order; use explicit trace-first candidate or native learned-profile saving, then benchmark independently')
    (ROOT/'output/verification/cache-learning-audit-20261009.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':main()
