"""Run serial, isolated IQ3_XXS arms and restore the installed profile afterward."""
import json
import argparse
import datetime
import socket
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = ROOT/'strata-iq3_xxs.json'
cfg = json.loads(BASE.read_text(encoding='utf-8'))
out = ROOT/'output/verification'
out.mkdir(parents=True, exist_ok=True)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--plan', choices=('source','tune','confirm'), default='source')
plan = parser.parse_args().plan
if 'iq3_xxs' not in cfg.get('model_name','').lower():
    raise RuntimeError('This validation requires IQ3_XXS')
try:
    with socket.create_connection(('127.0.0.1',8088),timeout=2):
        raise RuntimeError('Port 8088 already in use. Stop the dedicated service before benchmarking.')
except OSError:
    pass
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')

def start(config,label):
    stdout = (out/f'{label}-server.log').open('w',encoding='utf-8')
    p = subprocess.Popen([sys.executable,'serve/server.py','--engine','strata','--config',str(config),'--port','8088','--lazy','--api-monitor','--idle-unload','900'],cwd=ROOT,stdout=stdout,stderr=subprocess.STDOUT)
    deadline = time.monotonic()+40
    while time.monotonic()<deadline:
        if p.poll() is not None:
            stdout.close()
            raise RuntimeError(f'{label}: server exited {p.returncode}')
        try:
            if 'ready: http://127.0.0.1:8088/' not in (out/f'{label}-server.log').read_text(encoding='utf-8'):
                time.sleep(.3)
                continue
            with urllib.request.urlopen('http://127.0.0.1:8088/health',timeout=2) as r:
                json.load(r)
            return p,stdout
        except OSError:
            time.sleep(.3)
    p.terminate();stdout.close()
    raise RuntimeError(f'{label}: readiness timeout')

def stop(p,stdout):
    p.terminate()
    try:p.wait(timeout=30)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=10)
    stdout.close()
    time.sleep(2)

plans = {
    'source': [('iq3-installed',None,{},{}),('iq3-source-control','build-hip/strata.exe',{'STRATA_HIP_WMMA':'0','STRATA_SELECT_WMMA':'0'},{}),
               ('iq3-source-wmma','build-hip/strata.exe',{'STRATA_HIP_WMMA':'1','STRATA_SELECT_WMMA':'0'},{})],
    'tune': [('iq3-paired-base',None,{},{}),('iq3-paired-spec2',None,{}, {'--spec':'2'}),
             ('iq3-paired-minp07',None,{}, {'--spec-min-p':'0.7'})],
    'confirm': [('iq3-confirm-minp07',None,{}, {'--spec-min-p':'0.7'}),('iq3-confirm-base',None,{}, {})],
}
arms = plans[plan]
try:
    for name,exe,env,flags in arms:
        label = stamp+'-'+name
        d = json.loads(json.dumps(cfg))
        if exe:d['exe'] = str(ROOT/exe)
        d.setdefault('env',{}).update(env)
        for flag,value in flags.items(): d['args'][d['args'].index(flag)+1] = value
        d['log'] = str(out/f'{label}-engine.log')
        path = out/f'{label}.json'
        from serve.configuration import atomic_json
        atomic_json(path,d)
        p,stdout = start(path,label)
        try:
            with (out/f'{label}-benchmark.log').open('w',encoding='utf-8') as f:
                subprocess.run([sys.executable,'tools/benchmark_local.py','--config',str(path),'--label',label,'--output',f'data/benchmarks/{label}.json'],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
        finally:stop(p,stdout)
        print(f'{label}: complete',flush=True)
finally:
    # Return the working installed IQ3_XXS service, even if an experimental arm fails.
    p,stdout = start(BASE,'iq3-final')
    print(f'IQ3_XXS installed server restored, pid {p.pid}',flush=True)
    stdout.close()
