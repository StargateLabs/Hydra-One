"""Isolated official Colibri launcher. Opening Strata never starts its engine."""
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

REVISION = 'bf2442915d6e3dd4cdfd2eb9c2a3d2aa44a25850'


def local_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or not parsed.port or parsed.port in (8090, 18198)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/', '/v1', '/v1/')):
        raise ValueError('Endpoint Colibri locale non valido')
    return value


class ColibriWorkspace:
    def __init__(self, root, idle):
        self.root = Path(root).resolve()
        self.idle = idle
        self.source = self.root / 'output/tools/colibri-runtime' / REVISION
        self.home = self.root / 'data/colibri'
        self.update_recovery_error=None
        try:
            from serve.colibri_update import recover_transition
            recover_transition(self.root)
        except (OSError,ValueError,KeyError,TypeError) as error:self.update_recovery_error=str(error)
        from serve.gpu_lease import recover_stale_colibri_reservation
        recover_stale_colibri_reservation(self.root)
        self.lock = threading.RLock()
        self.child = None
        self.job = {'state': 'idle'}
        self.rows = None
        self.lease = None
        self.api_endpoint = None

    def api_lease_matches(self, payload):
        """The API connector may share this reservation, never another engine's."""
        if not self.lease or not self.lease.held or not self.api_endpoint:
            return False
        try:
            marker=json.loads(self.lease.path.read_text(encoding='utf-8'))
            return (marker.get('token')==self.lease.token and marker.get('pid')==os.getpid()
                    and payload.get('url','').rstrip('/')==self.api_endpoint.rstrip('/'))
        except (OSError,ValueError):
            return False

    def _environment(self):
        return dict(os.environ, COLI_SETUP_HOME=str(self.home), PYTHONUTF8='1',
                    PYTHONUNBUFFERED='1')

    def _command(self, *args):
        if not (self.source / 'c/coli').is_file():
            raise ValueError('Sorgenti ufficiali Colibri non preparati')
        manifest = json.loads((self.source / 'STRATA-SOURCE.json').read_text(encoding='utf-8'))
        if manifest.get('revision') != REVISION:
            raise ValueError('Revisione Colibri non verificata')
        return [sys.executable, '-X', 'utf8', str(self.source / 'c/coli'), *args]

    def _json(self, *args):
        try:
            result = subprocess.run(self._command(*args), cwd=self.source,
                                    env=self._environment(), capture_output=True, text=True,
                                    encoding='utf-8', timeout=35,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as error:
            raise ValueError('Colibri non ha risposto entro 35 secondi; consulta il registro originale') from error
        if result.returncode:
            raise ValueError((result.stderr or result.stdout)[-1200:])
        return json.loads(result.stdout)

    def catalogue(self):
        with self.lock:
            if self.rows is None:
                rows = self._json('setup', '--list', '--json')
                if not isinstance(rows, list):
                    raise ValueError('Catalogo originale Colibri non valido')
                self.rows = rows
            return self.rows

    def status(self):
        with self.lock:
            installed = (self.source / 'c/coli').is_file()
            native = self._json('status', '--json') if installed else {}
            server = native.get('server') or {}
            urls = server.get('urls') or {}
            safe = {}
            for key in ('browser', 'openai_base_url', 'anthropic_base_url'):
                if urls.get(key):
                    safe[key] = local_url(urls[key])
            running = server.get('state') in ('ready', 'loading')
            if not running and self.lease:
                self.lease.release()
                self.lease = None
                self.api_endpoint = None
            preparing = (self.child is not None and self.child.poll() is None) or bool((native.get('install') or {}).get('running'))
            return dict(installed=installed, revision=REVISION, native=native,runtime_update_error=self.update_recovery_error,
                        job=dict(self.job), busy=preparing or running,
                        status='preparing' if preparing else server.get('state', 'unconfigured'),
                        urls=safe, model_id=server.get('model_id'),
                        automatic_start=False, scope='original_isolated_workspace')

    def prepare(self, payload):
        with self.lock:
            if not self.idle():
                raise ValueError('Termina le attività prima di preparare Colibri')
            if self.status()['busy']:
                raise ValueError('Colibri è già attivo o in preparazione')
            row = next((r for r in self.catalogue() if r.get('id') == payload.get('model')), None)
            if not row or not row.get('fits'):
                raise ValueError('Scegli un modello compatibile dal catalogo originale')
            expected = int(float(row['download_gb']) * 10**9)
            if type(payload.get('confirmed_bytes')) is not int or payload['confirmed_bytes'] != expected:
                raise ValueError('Controlla e conferma la dimensione del download selezionato')
            if shutil.disk_usage(self.root).free < expected + 2 * 1024**3:
                raise ValueError('Spazio insufficiente: conserva anche 2 GiB di riserva')
            self.home.mkdir(parents=True, exist_ok=True)
            command = self._command('setup', '--yes', '--model', row['id'], '--no-start',
                                    '--dir', str(self.root / 'models/colibri'),
                                    '--host', '127.0.0.1', '--port', '18889', '--no-browser')
            self.job = {'state': 'preparing', 'model': row['id'], 'bytes': expected}
            with (self.home / 'setup.log').open('ab') as log:
                self.child = subprocess.Popen(command, cwd=self.source, env=self._environment(),
                                              stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            threading.Thread(target=self._wait, args=(self.child,), daemon=True, name='colibri-setup').start()
            return self.status()

    def _wait(self, child):
        result = child.wait()
        with self.lock:
            if self.child is child:
                self.job.update(state='configured' if result == 0 else 'error', returncode=result,
                                log='data/colibri/setup.log')

    def api_metadata(self,payload):
        if not self.api_lease_matches(payload):return {}
        limits=self.context_configuration()
        return dict(model_max_context=limits['maximum'],active_context=limits.get('active'),context_source='owned_colibri_runtime')

    def context_configuration(self):
        config=json.loads((self.home/'setup.json').read_text(encoding='utf-8'))
        family=config.get('family')
        if getattr(self,'_family_limits',{}).get('family')!=family:
            code="import json,sys;from family_registry import family_by_id;f=family_by_id(sys.argv[1]);print(json.dumps(dict(family=f.id,default=f.limits.default_context,maximum=f.limits.max_context,environment=f.limits.context_env)))"
            result=subprocess.run([sys.executable,'-X','utf8','-c',code,family],cwd=self.source/'c',env=self._environment(),capture_output=True,text=True,encoding='utf-8',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError('Limiti del contesto Colibri non leggibili')
            self._family_limits=json.loads(result.stdout)
        limits=dict(self._family_limits)
        saved=(config.get('env') or {}).get(limits['environment'])
        limits['configured']=int(saved or limits['default'])
        args=config.get('args') or [];limits['runtime']={'ram':0,'vram':0,'policy':'quality','repin':0,'kv_slots':1,'max_queue':8,'queue_timeout':300}
        limits['runtime_sources']={key:'native_default' for key in limits['runtime']}
        if family=='qwen36':limits['runtime']['cap']=8;limits['runtime_sources']['cap']='native_family_default'
        for key,flag in self.RUNTIME_FLAGS.items():
            if flag in args and args.index(flag)+1<len(args):
                limits['runtime'][key]=args[args.index(flag)+1];limits['runtime_sources'][key]='saved_configuration'
        limits['runtime']['auto_tier']='--auto-tier' in args
        try:
            marker=json.loads((self.home/'strata-runtime.json').read_text(encoding='utf-8'))
            native=self._json('status','--json')
            limits['active']=marker.get('context') if marker.get('pid')==(native.get('server') or {}).get('pid') else None
        except (OSError,ValueError):limits['active']=None
        return limits

    RUNTIME_FLAGS={'ram':'--ram','vram':'--vram','policy':'--policy','repin':'--repin','cap':'--cap','kv_slots':'--kv-slots','max_queue':'--max-queue','queue_timeout':'--queue-timeout'}

    def configure_context(self,payload):
        limits=self.context_configuration()
        context=payload.get('context')
        if type(context) is not int or not 1024<=context<=limits['maximum']:
            raise ValueError('Contesto fuori dai limiti del modello')
        config=json.loads((self.home/'setup.json').read_text(encoding='utf-8'))
        runtime=payload.get('runtime',{})
        if not isinstance(runtime,dict) or runtime.keys()-set(self.RUNTIME_FLAGS)-{'auto_tier'}:raise ValueError('Parametri Colibri non validi')
        ranges={'ram':(0,1024),'vram':(0,1024),'repin':(0,65536),'cap':(1,1024),'kv_slots':(1,16),'max_queue':(0,1024),'queue_timeout':(1,3600)}
        for key,value in runtime.items():
            if key=='auto_tier':
                if type(value) is not bool:raise ValueError('Pianificazione automatica non valida')
            elif key=='policy':
                if value not in ('','quality','balanced','experimental-fast'):raise ValueError('Profilo risorse non valido')
            elif type(value) not in (int,float) or not ranges[key][0]<=value<=ranges[key][1] or (key not in ('vram','queue_timeout') and type(value) is not int):raise ValueError('Valore non valido: '+key)
        args=list(config.get('args') or [])
        for key,value in runtime.items():
            flag='--auto-tier' if key=='auto_tier' else self.RUNTIME_FLAGS[key]
            while flag in args:
                index=args.index(flag);del args[index:index+(1 if key=='auto_tier' else 2)]
            if key=='auto_tier':
                if value:args.append(flag)
            elif not (key=='policy' and value==''):args.extend([flag,str(value)])
        config['args']=args
        config.setdefault('env',{})[limits['environment']]=str(context)
        config['env']['CTX']=str(context)
        target=self.home/'setup.json';temporary=target.with_suffix('.strata.tmp')
        temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(target)
        return self.context_configuration()

    def start(self):
        with self.lock:
            state = self.status()
            if not state['installed'] or not state['native'].get('configured'):
                raise ValueError('Prepara prima runtime e modello Colibri dal catalogo originale')
            if state['busy']:
                return state
            if not self.idle():
                raise ValueError('Termina le attività e scarica i modelli prima di avviare Colibri')
            config = json.loads((self.home / 'setup.json').read_text(encoding='utf-8'))
            if config.get('host') != '127.0.0.1':
                raise ValueError('Colibri deve restare su loopback')
            limits=self.context_configuration()
            if limits['environment'] not in (config.get('env') or {}) and limits['maximum']>=65536:
                self.configure_context({'context':65536})
            from serve.gpu_lease import GpuLease
            self.lease = GpuLease(self.root,'colibri-original-workspace').acquire()
            try:
                started=self._json('start', '--background', '--no-browser', '--json')
                self.api_endpoint=local_url((started.get('urls') or {})['openai_base_url'])
                native=self._json('status','--json');actual=self.context_configuration()
                (self.home/'strata-runtime.json').write_text(json.dumps(dict(pid=(native.get('server') or {}).get('pid'),context=actual['configured'])),encoding='utf-8')
            except BaseException:
                # A timeout can leave the native background server running. Keep
                # its reservation until native status proves the server stopped.
                try:
                    native=self._json('status','--json')
                    if (native.get('server') or {}).get('state') not in ('ready','loading'):
                        self.lease.release();self.lease=None
                except (OSError,ValueError):pass
                raise
            return self.status()

    def monitor_snapshot(self):
        import time,copy
        cached=getattr(self,'_monitor',{})
        if not self.api_endpoint:return {}
        now=time.monotonic()
        if now-getattr(self,'_monitor_at',0)>2 and not getattr(self,'_monitor_pending',False):
            self._monitor_pending=True;self._monitor_at=now
            endpoint=self.api_endpoint
            def sample():
                import urllib.request
                result={'updated_at':time.time()}
                try:
                    for name in ('health','profile','experts'):
                        with urllib.request.urlopen(endpoint.removesuffix('/v1')+'/'+name,timeout=1) as response:
                            raw=response.read(2*1024**2+1)
                        if len(raw)>2*1024**2:raise ValueError('Telemetria troppo grande')
                        result[name]=json.loads(raw)
                    if self.api_endpoint==endpoint:self._monitor=result
                except (OSError,ValueError):
                    if self.api_endpoint==endpoint:self._monitor={'unavailable':True,'updated_at':time.time()}
                finally:self._monitor_pending=False
            threading.Thread(target=sample,daemon=True).start()
        return copy.deepcopy(cached)

    def close(self):
        # Upstream can contain requests that Strata cannot inspect. Preserve it.
        return None
