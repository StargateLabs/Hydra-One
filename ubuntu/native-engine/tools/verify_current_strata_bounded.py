"""Isolated release check: one eight-token answer, limited cache and resource watchdog."""
import argparse,hashlib,json,os,subprocess,sys,time,threading
from pathlib import Path
from urllib.request import Request,urlopen
import psutil
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
PORT=8094
DASHBOARD_PORTS=(8090,8088,8080)
def dashboard_port():
    """The Strata dashboard this PC is currently running, whichever port it chose."""
    for port in DASHBOARD_PORTS:
        try:
            health=call(port,'/health',timeout=2)
        except Exception:continue
        if isinstance(health,dict) and health.get('service')=='strata':return port
    raise RuntimeError('no Strata dashboard is listening on this PC; start it before validating a candidate')
def call(port,path,body=None,timeout=4):
    req=Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=timeout) as response:return json.load(response)
def stop_owned(process):
    if process is None:return
    try:
        owner=psutil.Process(process.pid);children=owner.children(recursive=True)
        for child in children:
            try:child.terminate()
            except psutil.Error:pass
        owner.terminate()
        _,alive=psutil.wait_procs(children+[owner],timeout=4)
        for child in alive:
            try:child.kill()
            except psutil.Error:pass
    except psutil.Error:pass
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--full-profile',action='store_true');options=parser.parse_args()
    report=dict(passed=False,scope='Isolated Strata 0.1.42 HIP, one 8-token request, 1K context, 1024 expert slots; not a throughput benchmark',started_at=time.time())
    child=None;lease=None;done=threading.Event();error=[];samples=[]
    try:
        port=dashboard_port()
        if call(port,'/metrics')['live']['state']!='unloaded' or call(port,'/inference-backends')['status']!='idle':raise RuntimeError('Dashboard engines must be unloaded')
        if (ROOT/'data/.gpu-campaign.lock').exists():raise RuntimeError('A GPU operation already owns the reservation')
        if not json.loads((ROOT/'output/verification/amd-gpu-bounded-probe.json').read_text(encoding='utf-8'))['passed']:raise RuntimeError('GPU probe failed')
        from serve.gpu_lease import GpuLease
        lease=GpuLease(ROOT,'strata-bounded-check').acquire()
        selected=json.loads((ROOT/'data/strata-runtime-selection.json').read_text(encoding='utf-8'))['active']
        directory=Path(selected['directory']).resolve()
        if not directory.is_relative_to((ROOT/'output/updates/candidates').resolve()):raise RuntimeError('Selected runtime outside managed candidates')
        build=json.loads((directory/'BUILD.json').read_text(encoding='utf-8'));expected_version=str(build['version'])
        config_path=Path(call(port,'/config')['config']);config_path=config_path if config_path.is_absolute() else ROOT/config_path
        cfg=json.loads(config_path.read_text(encoding='utf-8-sig'))
        cfg.update(exe=str(directory/'strata.exe'),lib_dirs=[str((directory/name).resolve()) for name in build.get('lib_dirs',[])])
        cfg.pop('api_key',None)
        args=cfg['args']
        original_args=list(args)
        for key,value in [('--expert-cache','1024'),('--max-context','1024'),('--kv-resident','1024'),('--spec','2'),('--prefill','256'),('--pool-workers','8'),('--vram-reserve-mib','4096'),('--resident-budget-gib','4')]:
            if key in args:args[args.index(key)+1]=value
            else:args.extend([key,value])
        if options.full_profile:
            cfg['args']=original_args
            report['scope']=f'Isolated Strata {expected_version} {build.get("backend","unknown")}, one 8-token response using the current operating arguments; not a throughput benchmark'
        else:
            report['scope']=f'Isolated Strata {expected_version}, one 8-token response with limited cache; not a throughput benchmark'
        cfg.update(log=str(ROOT/'output/verification/strata-candidate-bounded-engine.log'),api_monitor=False,lazy_load=True)
        report['full_profile']=options.full_profile
        report['exe_sha256']=hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest()
        report['validated_configuration']=cfg
        path=ROOT/'output/verification/strata-current-audit-20261015-bounded-config.json';path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        with (ROOT/'output/verification/strata-current-audit-20261015-bounded-server.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'serve/server.py'),'--engine','strata','--config',str(path),'--lazy','--port',str(PORT),'--host','127.0.0.1'],cwd=ROOT,env={**os.environ,'STRATA_VALIDATION_LEASE_TOKEN':lease.token},stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline=time.monotonic()+180
            def watch():
                while not done.wait(.5):
                    free=psutil.virtual_memory().available/2**30
                    samples.append({'at':time.time(),'ram_free_gib':free})
                    if free<10 or time.monotonic()>deadline:
                        error.append('RAM reserve below 10 GiB' if free<10 else '180-second total deadline reached');stop_owned(child);return
            threading.Thread(target=watch,daemon=True).start()
            ready=time.monotonic()+20
            while time.monotonic()<ready:
                if child.poll() is not None:raise RuntimeError('Isolated server exited')
                try:model=call(PORT,'/v1/models')['data'][0]['id'];break
                except (OSError,ValueError):time.sleep(.25)
            else:raise RuntimeError('Isolated endpoint failed to start')
            response=call(PORT,'/v1/chat/completions',dict(model=model,messages=[dict(role='user',content='Say hello briefly.')],max_tokens=8,temperature=0,stream=False,chat_template_kwargs={'enable_thinking':False}),timeout=170)
            metrics=call(PORT,'/metrics')
            answer=response['choices'][0]['message'].get('content')
            version=str(metrics.get('engine',{}).get('version',''))
            report.update(response=response,engine=metrics.get('engine'),live=metrics.get('live'),model=model)
            if not answer or version!=expected_version:raise RuntimeError('Empty response or wrong engine version: '+version)
            report.update(passed=True,response=response,engine=metrics.get('engine'),live=metrics.get('live'),model=model)
    except Exception as exception:report['error']=str(exception)
    finally:
        done.set();stop_owned(child);
        if lease:lease.release()
        report.update(watchdog_errors=error,resource_samples=samples,finished_at=time.time())
        if error:report['passed']=False
        (ROOT/'output/verification/strata-current-audit-20261015-bounded-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        (ROOT/'output/verification/strata-current-audit-inference-20261015.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in ('resource_samples','response','live','engine','validated_configuration')},indent=2))
    raise SystemExit(0 if report['passed'] else 1)
if __name__=='__main__':main()
