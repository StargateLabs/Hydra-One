"""Explicit standalone addon. Nothing starts without --enable."""
import argparse
from dataclasses import replace
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
from urllib.parse import urlsplit

from hydra_hybrid.config import Config, host_resources
from hydra_hybrid.backend import HydraAdapter, HTTPBackend, launch_plan
from hydra_hybrid.process import OwnedProcess
from .bridge import Bridge
from .upstream import ServiceAdapter


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--enable',action='store_true')
    parser.add_argument('--launch-native',action='store_true')
    parser.add_argument('--attach-service',action='store_true')
    parser.add_argument('--session-dir')
    parser.add_argument('--port',type=int,default=18897)
    parser.add_argument('--strata-root')
    args=parser.parse_args()
    config=Config.load(args.config)
    if not args.enable:
        print(json.dumps(dict(state='disabled',listener_started=False,native_started=False)))
        return 0
    if not args.session_dir or args.launch_native==args.attach_service:
        parser.error('Choose exactly one of --launch-native/--attach-service and a NEW --session-dir')
    directory=Path(args.session_dir).resolve();directory.mkdir(parents=True,exist_ok=False)
    config=replace(config,enabled=True,live_io_authorized=True,native_execution_authorized=args.launch_native)
    token=secrets.token_urlsafe(32)
    with (directory/'local-api-key.txt').open('x',encoding='utf-8') as keyfile:keyfile.write(token)
    # Local access secret, intentionally excluded from manifests and console output.
    owner=OwnedProcess();adapter=bridge=observer=probe=None;native_log=None
    status=dict(state='starting',collection_authorized=False,model=config.model)
    try:
        resources=host_resources
        if config.gpu_layers:
            if not args.strata_root:raise ValueError('GPU mode requires --strata-root for the existing reservation preflight')
            from hydra_lab.baseline import require_idle
            require_idle(Path(args.strata_root))
            from .observer import HIPObserver
            observer=HIPObserver(Path(config.binary).parent)
            resources=lambda:observer.sample()[0]
        if args.launch_native:
            probe=HTTPBackend(config)
            if probe.prepare()['state']!='prepared':raise ValueError('Pinned native model/backend unavailable')
            with socket.socket() as chosen:
                chosen.bind(('127.0.0.1',0));port=chosen.getsockname()[1]
            config=replace(config,backend_url='http://127.0.0.1:'+str(port))
            native_log=(directory/'native.log').open('xb')
            def spawn(argv,**kwargs):
                kwargs.update(cwd=directory,env=dict(os.environ,GGML_BACKEND_PATH=str(Path(config.binary).parent)),
                              stdout=native_log,stderr=subprocess.STDOUT)
                return subprocess.Popen(argv,**kwargs)
            owner=OwnedProcess(spawn=spawn)
            argv=launch_plan(config,port=port)
            if observer is not None:argv[argv.index('--device')+1]='ROCm'+str(observer.device)
            child=owner.start(argv,authorized=True)
            # File identity was verified before launch; probe readiness is not a hardware claim.
            probe.close();probe=HTTPBackend(config)
            if probe.prepare()['state']!='prepared':raise ValueError('Reconfigured native probe identity unavailable')
            end=time.monotonic()+60
            while True:
                if child.poll() is not None:raise RuntimeError('Native process terminated during load')
                try:
                    if probe.health(deadline=time.monotonic()+1)['state']=='ready':break
                except (ConnectionRefusedError,TimeoutError):pass
                if time.monotonic()>end:raise TimeoutError('Native readiness timeout')
                time.sleep(.1)
            probe.close();probe=None
            adapter=HydraAdapter(config,resources=resources)
        else:
            adapter=ServiceAdapter(config,resources=resources)
        identity=adapter.prepare()
        if identity['state']!='prepared':raise RuntimeError('Backend preparation failed')
        bridge=Bridge(adapter,config.model,config.context,port=args.port,token=token)
        bridge.start()
        status.update(state='running',url='http://127.0.0.1:'+str(bridge.address[1])+'/v1',
                      upstream=config.backend_url,
                      key_file=str(directory/'local-api-key.txt'),native_pid=owner.child.pid if owner.child else None,
                      backend_identity=identity,physical_nvme_verified=False)
        with (directory/'connection.json').open('x',encoding='utf-8') as f:json.dump(status,f,indent=2)
        print(json.dumps(status),flush=True)
        while bridge.thread.is_alive() and not (directory/'STOP').exists():time.sleep(.2)
    except KeyboardInterrupt:
        status['stop']='keyboard_interrupt'
    except Exception as exc:
        status.update(state='failed',error_type=type(exc).__name__,message=str(exc))
    finally:
        errors=[]
        try:
            if bridge is not None:
                if not bridge.close():errors.append('Bridge drain uncertain')
            elif adapter is not None and not adapter.close():errors.append('Adapter drain uncertain')
            if probe is not None:probe.close()
        except Exception as exc:errors.append('Bridge/adapter: '+str(exc))
        try:
            if not owner.close():errors.append('Native owner drain uncertain')
        except Exception as exc:errors.append('Native owner: '+str(exc))
        if observer is not None:observer.close()
        if native_log is not None:native_log.close()
        status.update(cleanup_errors=errors,cleanup_complete=not errors)
        if errors:status['state']='shutdown_uncertain'
        elif status.get('state')!='failed':status['state']='closed'
        with (directory/'shutdown.json').open('x',encoding='utf-8') as f:json.dump(status,f,indent=2)
        print(json.dumps(status),flush=True)
    return 0 if status['state']=='closed' else 2


if __name__=='__main__':raise SystemExit(main())
