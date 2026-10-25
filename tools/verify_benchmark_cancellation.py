"""Exercise owned live job cancellation and conflicting starts on the local UI API."""
import json
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8088'
def call(path,data=None):
    req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':BASE})
    with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
def main():
    request=dict(model='strata-iq3_xxs.json',mode='manual',variants=['auto'],tokens=128,runs=5,paragraphs=8,quality=False)
    job=call('/benchmark-lab/start',request);identity=job['id'];checks={}
    try:
        for path,payload,name in (('/benchmark-lab/start',request,'parallel_start'),('/load',{},'operational_load')):
            try:call(path,payload);raise RuntimeError('Conflicting GPU action accepted')
            except urllib.error.HTTPError as exc:
                if exc.code not in ((409,) if name=='parallel_start' else (409,503)):raise
                checks[name]=exc.code
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            current=call('/benchmark-lab')['job']
            if current['id']!=identity:raise RuntimeError('Owned job replaced')
            if current.get('completed_samples',0)>=1:break
            if current['status'] not in ('queued','running'):raise RuntimeError(str(current))
            time.sleep(1)
        else:raise RuntimeError('No completed request within deadline')
        checks['completed_before_stop']=current['completed_samples'];checks['stop_response']=call('/benchmark-lab/stop',{})
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            current=call('/benchmark-lab')['job']
            if current['status']=='cancelled' and not (ROOT/'data/.gpu-campaign.lock').exists():break
            time.sleep(1)
        else:raise RuntimeError('Cancellation did not finish cleanup')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8089))==0:raise RuntimeError('Owned server still listening')
        if call('/metrics')['live']['state']!='unloaded':raise RuntimeError('Operational model was loaded')
        checks.update(job_id=identity,status=current['status'],gpu_reservation_released=True,isolated_port_released=True,operational_unloaded=True)
        (ROOT/'output/verification/benchmark-cancellation-live.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))
    finally:
        latest=call('/benchmark-lab')['job']
        if latest['id']==identity and latest['status'] in ('queued','running','cancelling'):call('/benchmark-lab/stop',{})
if __name__=='__main__':main()
