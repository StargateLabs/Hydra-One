"""Run three owned, bounded copy tests while no Strata model is active."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.gpu_lease import GpuLease

def main():
    target=ROOT/'output/verification/host-blit-results.json'
    exe=ROOT/'output/verification/host-blit-probe.exe'
    env=dict(os.environ);env['PATH']=str(ROOT/'engine')+os.pathsep+env['PATH']
    report={'status':'running','scope':'Synthetic mapped host copy; not LLM throughput','started_at':time.time(),
            'binary_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'runs':[]}
    def save():target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    with GpuLease(ROOT,'host-blit-probe'):
        metrics=json.load(urllib.request.urlopen('http://127.0.0.1:8088/metrics',timeout=5))
        if metrics['live']['state']!='unloaded' or metrics['live'].get('queued'):raise RuntimeError('Operational model must be unloaded and idle')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8089))==0:raise RuntimeError('Isolated server active')
        try:
            for index in range(3):
                run=subprocess.run([str(exe)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
                (target.parent/f'host-blit-run-{index+1}.log').write_text(run.stdout+run.stderr,encoding='utf-8')
                if run.returncode:raise RuntimeError(f'Probe exited {run.returncode}; no engine change permitted')
                rows=[json.loads(line) for line in run.stdout.splitlines() if line.startswith('{')]
                if len(rows)!=12 or any(r['verified_bytes']!=r['bytes'] or r['median_gbps']<=0 for r in rows):raise RuntimeError('Incomplete or invalid copy evidence')
                report['runs'].append({'index':index+1,'rows':rows});save()
            report['status']='complete'
        except Exception as exc:report.update(status='failed',error=str(exc));raise
        finally:report['finished_at']=time.time();save()
    for run in report['runs']:
        print('run',run['index'],[(r['mode'],round(r['median_gbps'],2)) for r in run['rows'] if r['bytes']==256<<20])
if __name__=='__main__':main()
