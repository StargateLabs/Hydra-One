"""Isolated release check: one sixty-four-token answer, limited cache and resource watchdog."""
import argparse,hashlib,json,subprocess,sys,time,threading
from pathlib import Path
from urllib.request import Request,urlopen
import psutil
ROOT=Path(__file__).resolve().parents[1]
PORT=8094
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
    report=dict(passed=False,scope='Isolated Strata 0.1.42 HIP, one 64-token request, 1K context, 1024 expert slots; not a throughput benchmark',started_at=time.time())
    child=None;lease=None;done=threading.Event();error=[];samples=[]
    try:
        if call(8088,'/metrics')['live']['state']!='unloaded' or call(8088,'/inference-backends')['status']!='idle':raise RuntimeError('Dashboard engines must be unloaded')
        if (ROOT/'data/.gpu-campaign.lock').exists():raise RuntimeError('A GPU operation already owns the reservation')
        if not json.loads((ROOT/'output/verification/amd-gpu-bounded-probe.json').read_text(encoding='utf-8'))['passed']:raise RuntimeError('GPU probe failed')
        from serve.gpu_lease import GpuLease
        lease=GpuLease(ROOT,'strata-bounded-check').acquire()
        selected=json.loads((ROOT/'data/strata-runtime-selection.json').read_text(encoding='utf-8')).get('active')
        job=json.loads((ROOT/'data/update-job.json').read_text(encoding='utf-8'))
        directory=Path(selected['directory'] if selected else job['result']['candidate_directory']).resolve()
        if (not selected and job.get('component')!='strata') or not directory.is_relative_to((ROOT/'output/updates/candidates').resolve()):raise RuntimeError('No isolated Strata candidate')
        build=json.loads((directory/'BUILD.json').read_text(encoding='utf-8'));expected_version=str(build['version'])
        config_path=Path(call(8088,'/config')['config']);config_path=config_path if config_path.is_absolute() else ROOT/config_path
        cfg=json.loads(config_path.read_text(encoding='utf-8-sig'))
        cfg.update(exe=str(directory/'strata.exe'),lib_dirs=[str((directory/name).resolve()) for name in build.get('lib_dirs',[])])
        cfg.pop('api_key',None)
        args=cfg['args']
        for key,value in [('--expert-cache','1024'),('--max-context','1024'),('--kv-resident','1024'),('--spec','2'),('--prefill','256'),('--pool-workers','8'),('--vram-reserve-mib','4096'),('--resident-budget-gib','4')]:
            if key in args:args[args.index(key)+1]=value
            else:args.extend([key,value])
        if options.full_profile:
            for key,value in [('--expert-cache','auto'),('--max-context','131072'),('--kv-resident','32768'),('--prefill','512'),('--resident-budget-gib','8')]:args[args.index(key)+1]=value
            report['scope']='Isolated Strata 0.1.42 HIP, one 64-token response, 128K configured context, automatic expert cache, 4 GiB VRAM reserve; single short throughput sample; not a stability or long-context benchmark'
        cfg.update(env={},log=str(ROOT/'output/verification/strata-v0142-64token-engine.log'),api_monitor=False,lazy_load=True)
        report['full_profile']=options.full_profile
        report['exe_sha256']=hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest()
        report['validated_configuration']=cfg
        path=ROOT/'output/verification/strata-v0142-64token-config.json';path.write_text(json.dumps(cfg,indent=2),encoding='utf-8')
        with (ROOT/'output/verification/strata-v0142-64token-server.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'serve/server.py'),'--engine','strata','--config',str(path),'--lazy','--port',str(PORT),'--host','127.0.0.1'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
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
            response=call(PORT,'/v1/chat/completions',dict(model=model,messages=[dict(role='user',content='Write a continuous story about a traveller visiting a library. Continue for at least 300 words.')],max_tokens=64,temperature=0,stream=False,chat_template_kwargs={'enable_thinking':False}),timeout=170)
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
        (ROOT/'output/verification/strata-v0142-64token-real.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        (ROOT/'output/verification/strata-v0142-64token-candidate.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key not in ('resource_samples','response','live','engine','validated_configuration')},indent=2))
    raise SystemExit(0 if report['passed'] else 1)
if __name__=='__main__':main()
