"""Guarded numerical check; no model loaded and no promotion from kernel timings."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.configuration import atomic_json
from serve.gpu_lease import GpuLease
BUILD=ROOT/'build-hc-small-window-01403'

def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8088'+path,timeout=5) as response:return json.load(response)

def main():
    identity=json.loads((ROOT/'output/verification/hc-small-window-source.json').read_text())
    if identity.get('quarantined'):raise RuntimeError('Candidate quarantined after launch failure 719; no GPU diagnostic permitted')
    if get('/metrics')['live']['state']!='unloaded' or get('/inference-backends')['status']!='idle':raise RuntimeError('Both model engines must be unloaded')
    report=dict(started_at=time.time(),model_loaded=False,passed=False,scope='Existing release gr_parity selftest with the gfx1100 small-window dispatcher enabled')
    with GpuLease(ROOT,'hc-small-window-parity'):
        runtime=BUILD/'amdhip64_7.dll'
        if hashlib.sha256(runtime.read_bytes()).digest()!=hashlib.sha256((ROOT/'engine/amdhip64_7.dll').read_bytes()).digest():raise RuntimeError('Runtime differs from installed control')
        env=dict(os.environ);env['STRATA_HC_SMALL_WINDOW']='1';env['STRATA_QFUSE']='0'
        logs=[]
        for name,args in [('strata-device',['--selftest']),('gr_parity',['--selftest'])]:
            result=subprocess.run([str(BUILD/(name+'.exe')),*args],cwd=BUILD,env=env,capture_output=True,text=True,timeout=60)
            body=result.stdout+result.stderr;logs.append(body)
            (ROOT/f'output/verification/hc-small-window-{name}.log').write_text(body,encoding='utf-8')
            report[name]=dict(returncode=result.returncode,windows_status=f'0x{result.returncode&0xffffffff:08x}')
            atomic_json(ROOT/'output/verification/hc-small-window-parity.json',report)
            if result.returncode:raise RuntimeError(f'{name} failed; model test not permitted')
        report['activated']='strata HC small-window active:' in logs[-1]
        report['passed']=report['activated'] and 'gr_parity OK' in logs[-1]
        report['completed_at']=time.time()
        atomic_json(ROOT/'output/verification/hc-small-window-parity.json',report)
        if not report['passed']:raise RuntimeError('New dispatcher not demonstrated by numerical test; no model test permitted')
    print('Small-window numerical validation passed; model throughput still unmeasured')

if __name__=='__main__':main()
