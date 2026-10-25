"""Bounded local connector to the original VoiceStudio desktop/backend.

Official contracts: docs/mcp.md, docs/api-auth.md, backend/main.py and
backend/api/routers/openai_compat.py at github.com/debpalash/VoiceStudio.
No model installation, engine replacement or remote traffic is performed here.
"""
import base64
import ast
from contextlib import contextmanager
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'https://github.com/debpalash/VoiceStudio'
DEFAULT_URL = 'http://127.0.0.1:3900'

def _dictionary_entry(payload):
    if not isinstance(payload,dict):raise ValueError('Voce del dizionario non valida.')
    term=payload.get('term');replacement=payload.get('replacement','')
    if not isinstance(term,str) or not term.strip() or len(term)>200:raise ValueError('Termine: da 1 a 200 caratteri.')
    if not isinstance(replacement,str) or len(replacement)>500:raise ValueError('Pronuncia: massimo 500 caratteri.')
    body={'term':term.strip(),'replacement':replacement,'type':payload.get('type','respelling'),'language':payload.get('language') or '*','enabled':payload.get('enabled',True)}
    if body['type'] not in ('respelling','ipa','cmu'):raise ValueError('Tipo di pronuncia non valido.')
    if type(body['enabled']) is not bool:raise ValueError('Stato della pronuncia non valido.')
    if not isinstance(body['language'],str) or len(body['language'])>20:raise ValueError('Lingua non valida.')
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('VoiceStudio: redirect rifiutato per mantenere i dati sul PC.')


def desktop_executable():
    """Find default or custom NSIS installs; never accept an arbitrary command."""
    if os.name != 'nt': return None
    candidates = []
    # LOCALAPPDATA can be remapped by the calling host; retain the user's install.
    profile=os.environ.get('USERPROFILE')
    if profile:candidates.append(Path(profile)/'AppData/Local/Programs/VoiceStudio/VoiceStudio.exe')
    for variable, suffix in (('LOCALAPPDATA', 'Programs/VoiceStudio'), ('ProgramFiles', 'VoiceStudio'), ('ProgramFiles(x86)', 'VoiceStudio')):
        if os.environ.get(variable): candidates.append(Path(os.environ[variable]) / suffix / 'VoiceStudio.exe')
    import winreg
    key_path = r'Software\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as registry:
                    for index in range(winreg.QueryInfoKey(registry)[0]):
                        try:
                            with winreg.OpenKey(registry, winreg.EnumKey(registry, index)) as entry:
                                name = winreg.QueryValueEx(entry, 'DisplayName')[0]
                                if name != 'VoiceStudio': continue
                                location = winreg.QueryValueEx(entry, 'InstallLocation')[0]
                                if location: candidates.append(Path(location) / 'VoiceStudio.exe')
                        except OSError: continue
            except OSError: continue
    return next((path for path in candidates if path.is_file()), None)


def _cpu_backend_environment(desktop):
    """Use only the verified app-private CPU setup, invalidated by app updates."""
    if not os.environ.get('APPDATA'): return {}
    project=Path(os.environ['APPDATA'])/'VoiceStudio/runtime/project'
    python=project/'.venv/Scripts/python.exe'
    try:
        marker=json.loads((project/'strata-cpu-runtime.json').read_text(encoding='utf-8'))
        lock=hashlib.sha256((desktop.parent/'resources/uv.lock').read_bytes()).hexdigest()
        if marker.get('lock_sha256')!=lock or not python.is_file():return {}
    except (OSError,ValueError,AttributeError):return {}
    return {'OMNIVOICE_BACKEND_CMD':json.dumps([str(python),'-m','uvicorn','main:app','--app-dir','backend','--host','127.0.0.1','--port','3900']),
            'OMNIVOICE_TORCH_VARIANT':'cpu','OMNIVOICE_PRELOAD_CAPTURE_ASR':'0','OMNIVOICE_PRELOAD_WATERMARK':'0','OMNIVOICE_PRELOAD_TTS_ASR':'0'}


def desktop_inventory():
    """Read installed desktop metadata without contacting its optional backend."""
    path = desktop_executable()
    result = {'installed_version': None, 'installed_source': 'not_detected',
              'desktop_installed': path is not None, 'runtime_validated': False}
    if path is None:
        return result
    from serve.native_libraries import file_version
    try:
        version = file_version(path)
        if version:
            parts = version.split('.')
            if len(parts) == 4 and parts[-1] == '0':
                version = '.'.join(parts[:3])
            result.update(installed_version=version, installed_source='windows_file_version_resource')
    except (OSError, ValueError):
        pass
    return result


class VoiceStudio:
    def __init__(self, root=None, base_url=None, executable=None):
        self.base_url = (base_url or os.environ.get('STRATA_VOICESTUDIO_URL') or DEFAULT_URL).rstrip('/')
        parts = urllib.parse.urlsplit(self.base_url)
        try: port = parts.port
        except ValueError: raise ValueError('Porta VoiceStudio non valida.') from None
        if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not port or parts.username or parts.password or parts.path or parts.query or parts.fragment:
            raise ValueError('VoiceStudio richiede http://127.0.0.1:<porta>.')
        self._executable = Path(executable) if executable else None
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self._busy = threading.Lock()
        self.root = Path(root) if root else Path(__file__).resolve().parents[1]
        self._web_process = None
        self._start_lock = threading.Lock()
        self._web_validation_cache = None
        self._ownership_file=self.root/'data/voicestudio-web-owner.json'
        from serve.process_lifecycle import recover_owned_process
        self._web_process=recover_owned_process(self._ownership_file,self.root/'tools/voicestudio_original_web_host.py')
        if self._web_process is None and self.base_url==DEFAULT_URL:
            self._recover_legacy_host()

    def _recover_legacy_host(self):
        """Migrate ownership for this project's exact original host from older launches."""
        helper=self.root/'tools/voicestudio_original_web_host.py';executable=self.executable()
        if not helper.is_file() or executable is None:return
        import psutil
        backend=executable.parent/'resources/backend';matches=[]
        for process in psutil.process_iter(['pid','cmdline','create_time']):
            try:
                command=process.info['cmdline'] or []
                if str(helper) in command and '--backend' in command and str(backend) in command:matches.append(process)
            except psutil.Error:continue
        if len(matches)==1:
            from serve.process_lifecycle import RecoveredProcess
            from serve.configuration import atomic_json
            self._web_process=RecoveredProcess(matches[0]);self._ownership_file.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(self._ownership_file,{'pid':matches[0].pid,'created_at':matches[0].create_time()})

    def executable(self):
        path = self._executable or desktop_executable()
        return path if path is not None and path.is_file() else None

    def _request(self, route, payload=None, timeout=2, limit=1024*1024, method=None, raw_body=None, content_type=None):
        body = raw_body if raw_body is not None else json.dumps(payload).encode('utf-8') if payload is not None else None
        request = urllib.request.Request(self.base_url+route, data=body, method=method, headers={'Content-Type': content_type or 'application/json', 'Accept': 'application/json' if payload is None else 'audio/wav'})
        try:
            response = self._opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            marker = response.headers.get('x-omnivoice-backend')
            if not marker: raise RuntimeError('Il servizio locale non è identificato come VoiceStudio.')
            data = response.read(limit+1)
            if len(data)>limit: raise RuntimeError('Risposta VoiceStudio oltre il limite consentito.')
            if response.status >= 400:
                try:
                    detail = json.loads(data)
                    message = (detail.get('error') or {}).get('message') or detail.get('detail') or 'VoiceStudio non pronto.'
                except (ValueError, AttributeError): message = 'VoiceStudio non pronto.'
                raise RuntimeError(str(message)[:1000])
            return data, marker, response.headers.get('Content-Type', '')

    def status(self):
        path = self.executable()
        state = {'installed': path is not None, 'executable': str(path) if path else None,
                 'connected': False, 'version': None, 'device': None, 'base_url': self.base_url,
                 'mcp_url': self.base_url+'/mcp', 'repository': REPOSITORY, 'busy': self._busy.locked(),
                 'inference_verified': False, 'desktop_identity_verified': False,
                 'message': 'VoiceStudio non raggiungibile. Avvia l’app e completa la configurazione.',
                 'hardware_note': 'Il runtime PyTorch può usare CPU; audio.cpp offre un percorso Vulkan separato per GPU compatibili.'}
        try:
            raw, marker, _ = self._request('/health')
            health = json.loads(raw)
            if not isinstance(health, dict) or health.get('status') != 'ok':
                raise RuntimeError('VoiceStudio è in avvio o non è pronto.')
            state.update(connected=True, version=health.get('version') or marker, device=health.get('device'), message='Backend VoiceStudio collegato; generazione audio da verificare.')
            try:
                raw, _, _ = self._request('/engines/tts', timeout=5)
                payload=json.loads(raw);engines=payload.get('tts',payload)
                active = next((item for item in engines.get('backends', []) if item.get('id') == engines.get('active')), {})
                evidence = active.get('execution_evidence') or {}
                state.update(active_engine=engines.get('active'), active_engine_device=active.get('effective_device'),
                             active_engine_execution=evidence, active_engine_gpu_name=evidence.get('gpu_name'))
            except (OSError, ValueError, RuntimeError, AttributeError): pass
        except (OSError, ValueError, RuntimeError) as error:
            state['message'] = str(error)[:500] or state['message']
        state.update(self.web_ui())
        return state

    def web_ui(self):
        """Identify the exact original renderer, never a recreated interface."""
        path=self.executable()
        if path is None:return {'web_ui_available': False}
        index=path.parent/'resources/frontend/dist/index.html'
        manifest=self.root/'output/voicestudio/original-web-manifest.json'
        try:
            archive=path.parent/'resources/app.asar'
            signature=(index.stat().st_mtime_ns,index.stat().st_size,archive.stat().st_mtime_ns,archive.stat().st_size,manifest.stat().st_mtime_ns)
            if self._web_validation_cache and self._web_validation_cache[0]==signature:
                valid=self._web_validation_cache[1]
                return {'web_ui_available':valid,'web_url':self.base_url+'/' if valid else None}
            data=json.loads(manifest.read_text(encoding='utf-8'))
            entry=next(item for item in data['files'] if item['path']=='index.html')
            valid=index.is_file() and hashlib.sha256(index.read_bytes()).hexdigest()==entry['sha256']
            valid=valid and hashlib.sha256(archive.read_bytes()).hexdigest()==data['source_sha256']
            self._web_validation_cache=(signature,valid)
        except (OSError,ValueError,KeyError,StopIteration):valid=False
        return {'web_ui_available': valid, 'web_url': self.base_url+'/' if valid else None}

    def ensure_web(self):
        """Start original VoiceStudio privately, without opening a desktop window."""
        with self._start_lock:
            return self._ensure_web()

    def _ensure_web(self):
        capability=self.web_ui()
        if not capability['web_ui_available']:raise RuntimeError('Frontend originale non preparato o app aggiornata; riesegui la verifica degli asset.')
        try:
            raw,_,_=self._request('/api/health',timeout=2)
            if json.loads(raw).get('status')=='ok':return {'ok':True,'reused':True,**capability}
        except (OSError,RuntimeError,ValueError):pass
        if self.status()['connected']:
            raise RuntimeError('VoiceStudio Desktop occupa il backend locale. Chiudilo quando i lavori sono terminati, poi apri lo studio interno.')
        path=self.executable()
        environment=os.environ.copy();environment.update(_cpu_backend_environment(path))
        if not environment.get('OMNIVOICE_BACKEND_CMD'):raise RuntimeError('Runtime CPU privato non verificato; nessun avvio eseguito.')
        command=json.loads(environment['OMNIVOICE_BACKEND_CMD'])
        python=Path(command[0]);backend=path.parent/'resources/backend'
        helper=self.root/'tools/voicestudio_original_web_host.py'
        log=self.root/'output/voicestudio/web-host.log';log.parent.mkdir(parents=True,exist_ok=True)
        if self._web_process is not None and self._web_process.poll() is None:return {'ok':True,'starting':True,**capability}
        with log.open('ab') as output:
            self._web_process=subprocess.Popen([str(python),str(helper),'--backend',str(backend)],cwd=str(backend),
                env=environment,stdout=output,stderr=output,stdin=subprocess.DEVNULL,close_fds=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
        import psutil
        from serve.configuration import atomic_json
        self._ownership_file.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(self._ownership_file,{'pid':self._web_process.pid,'created_at':psutil.Process(self._web_process.pid).create_time()})
        return {'ok':True,'starting':True,'message':'Servizi vocali interni in avvio.',**capability}

    def ensure_mcp_ready(self):
        self.ensure_web()
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if self.status()['connected']:return
            if self._web_process is None or self._web_process.poll() is not None:
                raise RuntimeError('Avvio VoiceStudio interrotto; nessun servizio gestito attivo.')
            time.sleep(0.5)
        raise RuntimeError('VoiceStudio non è pronto dopo il tempo di avvio previsto.')

    @contextmanager
    def mcp_activity(self):
        from serve.mcp import McpError
        if not self._busy.acquire(blocking=False):raise McpError('Attendi la fine dell’attività vocale in corso.')
        try:yield
        finally:self._busy.release()

    def launch(self):
        """Activate only managed internal services, never an external desktop window."""
        return self.ensure_web()

    def stop(self):
        """Release only the original web host started by this connector."""
        with self._start_lock:
            if not self._busy.acquire(blocking=False):
                return {'ok':False,'busy':True}
            try:
                if self._web_process is None:return {'ok':True,'stopped':False,'managed':False}
                try:
                    raw,_,_=self._request('/models/install/status',timeout=3)
                    jobs=json.loads(raw).get('jobs',[])
                    if any(job.get('target')=='local' and job.get('state') in ('queued','running','downloading','installing') for job in jobs):
                        return {'ok':False,'busy':True}
                    for route in ('/jobs?status=active&limit=500','/batch/jobs?status=running&limit=500','/batch/jobs?status=queued&limit=500'):
                        raw,_,_=self._request(route,timeout=3)
                        data=json.loads(raw);rows=data if isinstance(data,list) else data.get('jobs') if isinstance(data,dict) else None
                        if not isinstance(rows,list):raise RuntimeError('Stato delle attività native non verificabile.')
                        if rows:return {'ok':False,'busy':True,'message':'Attività VoiceStudio native ancora in corso.'}
                except (OSError,ValueError,RuntimeError):
                    if self._web_process.poll() is None:return {'ok':False,'busy':True,'message':'Attività del servizio non verificabile.'}
                from serve.process_lifecycle import stop_owned_tree
                stop_owned_tree(self._web_process)
                self._web_process=None
                self._ownership_file.unlink(missing_ok=True)
                return {'ok':True,'stopped':True,'managed':True}
            finally:self._busy.release()

    def engines(self):
        self._ready()
        raw,_,_=self._request('/engines/tts',timeout=10)
        result=json.loads(raw)
        if not isinstance(result,dict) or not isinstance(result.get('backends'),list):raise RuntimeError('Elenco motori VoiceStudio non valido.')
        desktop=self.executable();catalog={}
        if desktop:
            source=desktop.parent/'resources/omnivoice/utils/lang_map.py'
            try:
                if source.stat().st_size>1024*1024:raise ValueError('Language catalogue exceeds bound')
                tree=ast.parse(source.read_text(encoding='utf-8-sig'))
                assignment=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='LANG_NAME_TO_ID' for target in node.targets))
                value=ast.literal_eval(assignment.value)
                if isinstance(value,dict):catalog={name:code for name,code in value.items() if isinstance(name,str) and isinstance(code,str) and len(name)<=64 and len(code)<=8}
            except (OSError,ValueError,SyntaxError,StopIteration):pass
            # The installed native audio.cpp adapter explicitly ignores speed.
            source=desktop.parent/'resources/backend/engines/audiocpp/__init__.py'
            try:
                if source.stat().st_size>1024*1024:raise ValueError('Adapter exceeds bound')
                text=source.read_text(encoding='utf-8-sig')
                if 'speed is not supported; ignoring.' in text:
                    for row in result['backends']:
                        if row.get('id')=='audiocpp':row['speech_controls']={'speed_supported':False,'evidence_source':'installed_original_adapter','source_sha256':hashlib.sha256(text.encode()).hexdigest()}
            except (OSError,ValueError):pass
        result['language_catalog']=catalog
        return result

    def select_engine(self,payload):
        if not self._busy.acquire(blocking=False):raise RuntimeError('Attendi la generazione audio prima di cambiare motore.')
        try:
            if not isinstance(payload,dict) or not isinstance(payload.get('backend_id'),str):raise ValueError('Seleziona un motore vocale.')
            inventory=self.engines()
            if inventory.get('env_override'):raise ValueError('Il profilo del servizio gestisce la scelta del motore.')
            entry=next((row for row in inventory['backends'] if row.get('id')==payload['backend_id']),None)
            if not entry or not entry.get('available') or entry.get('routing_status')=='unavailable':raise ValueError('Motore non disponibile su questo PC.')
            if entry.get('license_required') and not entry.get('license_accepted'):raise ValueError('Questo motore richiede accettazione della propria licenza.')
            raw,_,_=self._request('/engines/select',{'family':'tts','backend_id':entry['id']},timeout=30)
            result=json.loads(raw)
            return {'selection':result,'status':self.status()}
        finally:self._busy.release()

    def connect_mcp(self, root):
        """Persist the verified official MCP endpoint for the dashboard and harnesses."""
        self._ready()
        from serve.configuration import atomic_json
        root=Path(root);path=root/'data/mcp-dashboard.json'
        data=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'mcpServers':{}}
        if not isinstance(data,dict) or not isinstance(data.get('mcpServers'),dict):
            raise ValueError('Configurazione MCP esistente non valida; nessuna modifica effettuata.')
        entry={'url':self.base_url+'/mcp','autostart':False}
        if data['mcpServers'].get('voicestudio')!=entry:
            backup=root/'output/updates/backups'/('mcp-before-voicestudio-'+str(time.time_ns())+'.json')
            backup.parent.mkdir(parents=True,exist_ok=True)
            atomic_json(backup,data)
            data['mcpServers']['voicestudio']=entry
            path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,data)
        return {'ok':True,'configured':True,'restart_required':True,
                'message':'MCP VoiceStudio configurato. Si applica al prossimo avvio della dashboard e degli harness.'}

    def _ready(self):
        state = self.status()
        if not state['connected']: raise RuntimeError(state['message'])

    def voices(self):
        self._ready()
        raw, _, _ = self._request('/v1/audio/voices', timeout=30)
        data = json.loads(raw)
        if not isinstance(data, dict): raise RuntimeError('Elenco voci VoiceStudio non valido.')
        return data

    def workspace(self):
        """Read the original collections, without creating copies of user records."""
        self._ready()
        result={}
        for name in ('profiles','personalities','pronunciation'):
            raw,_,_=self._request('/'+name,timeout=15)
            rows=json.loads(raw)
            if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
                raise RuntimeError('Elenco VoiceStudio non valido: '+name)
            result[name]=rows
        from serve.voicestudio_profiles import design_catalog
        result['voice_design']=design_catalog(self.executable())
        return result

    def profile(self,payload):
        from serve.voicestudio_profiles import profile_action
        return profile_action(self,payload)

    def activities(self):
        from serve.voicestudio_jobs import activities
        return activities(self)

    def job_action(self,payload):
        from serve.voicestudio_jobs import action
        return action(self,payload)

    def pronunciation(self,payload):
        """Bounded dictionary adapter; never accepts a URL or a replacement import."""
        if not isinstance(payload,dict):raise ValueError('Dizionario vocale non valido.')
        action=payload.get('action')
        if action=='import':
            entries=payload.get('entries')
            if not isinstance(entries,list) or not 1<=len(entries)<=1000:raise ValueError('Importa da 1 a 1000 pronunce.')
            if payload.get('replace') not in (None,False):raise ValueError('L’importazione conserva le pronunce esistenti.')
            route='/pronunciation/import';body={'entries':[_dictionary_entry(row) for row in entries],'replace':False};method='POST'
        elif action=='preview':
            text=payload.get('text')
            if not isinstance(text,str) or not text.strip() or len(text)>4096:raise ValueError('Inserisci da 1 a 4096 caratteri.')
            route='/pronunciation/test';body={'text':text,'language':payload.get('language')};method='POST'
        elif action in ('add','update','delete'):
            identifier=str(payload.get('id',''))
            if action!='add' and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',identifier):raise ValueError('Voce del dizionario non valida.')
            route='/pronunciation'+('/'+identifier if action!='add' else '')
            method={'add':'POST','update':'PUT','delete':'DELETE'}[action]
            body=None
            if action!='delete':
                body=_dictionary_entry(payload)
        else:raise ValueError('Operazione dizionario non supportata.')
        language=(body or {}).get('language')
        if language is not None and (not isinstance(language,str) or len(language)>20):raise ValueError('Lingua non valida.')
        if not self._busy.acquire(blocking=False):raise RuntimeError('Attendi la fine della generazione vocale.')
        try:
            self._ready();raw,_,_=self._request(route,body,timeout=15,method=method)
            return {'ok':True,'result':json.loads(raw) if raw else {}}
        finally:self._busy.release()

    def setup(self):
        """Read official CPU/host recommendations without downloading or selecting engines."""
        self._ready()
        raw, _, _ = self._request('/setup/recommendations', timeout=30)
        recommendations = json.loads(raw)
        raw, _, _ = self._request('/api/settings/performance-profile', timeout=30)
        profile = json.loads(raw)
        raw, _, _ = self._request('/setup/status', timeout=30)
        status = json.loads(raw)
        return {'models': recommendations.get('models', []), 'device': recommendations.get('device'),
                'disk_free_gb': status.get('disk_free_gb'), 'min_free_gb': status.get('min_free_gb', 10),
                'performance_preset_applicable': bool(profile.get('applicable_families')),
                'engine_selections': profile.get('selections'), 'downloads_started': False}

    def install(self, payload):
        """Install one explicitly selected official recommended model, preserving engines."""
        if self._busy.locked(): raise RuntimeError('Attendi il completamento della generazione audio prima di installare modelli.')
        if not isinstance(payload, dict) or not isinstance(payload.get('repo_id'), str):
            raise ValueError('Seleziona un modello consigliato da VoiceStudio.')
        state = self.setup()
        model = next((item for item in state['models'] if item.get('repo_id') == payload['repo_id']), None)
        if model is None: raise ValueError('Modello non presente nei consigli ufficiali di VoiceStudio.')
        if model.get('installed'):
            return {'ok': True, 'already_installed': True, 'downloads_started': False,
                    'message': 'Modello già installato. Le selezioni dei motori sono state conservate.'}
        if payload.get('confirm') is not True: raise ValueError('Conferma il download del modello selezionato.')
        size = model.get('size_gb')
        free = state['disk_free_gb']
        if not isinstance(size, (int, float)) or not isinstance(free, (int, float)):
            raise RuntimeError('Spazio o dimensione del modello non disponibili; verifica il collegamento e riprova.')
        if free < size + state['min_free_gb']:
            raise RuntimeError('Spazio libero insufficiente per il modello e la riserva di VoiceStudio.')
        # Model installation has its own official API. Never set a global preset here:
        # KittenTTS/WhisperX/Argos can legitimately have no applicable tier families.
        raw, _, _ = self._request('/models/install', {'repo_id': model['repo_id'], 'target': 'local'}, timeout=30)
        return {'ok': True, 'downloads_started': True, 'result': json.loads(raw),
                'message': 'Installazione del modello richiesta. Aggiorna il pannello per verificare la disponibilità; motori conservati.'}

    def speech(self, payload):
        if not isinstance(payload,dict):raise ValueError('Richiesta audio VoiceStudio non valida.')
        text = payload.get('input')
        voice = payload.get('voice', 'default')
        if not isinstance(text, str) or not text.strip() or len(text)>4096: raise ValueError('Inserisci da 1 a 4096 caratteri.')
        if not isinstance(voice, str) or not voice or len(voice)>200: raise ValueError('Voce non valida.')
        language = payload.get('language')
        if language is not None and (not isinstance(language, str) or len(language)>20): raise ValueError('Lingua non valida.')
        speed=payload.get('speed',1.0)
        if type(speed) not in (int,float) or not math.isfinite(speed) or not 0.25<=speed<=4:
            raise ValueError('Velocità vocale consentita: da 0,25 a 4.')
        instructions=payload.get('instructions')
        if instructions is not None and (not isinstance(instructions,str) or len(instructions)>4096):
            raise ValueError('Indicazioni vocali: massimo 4096 caratteri.')
        if not self._busy.acquire(blocking=False): raise RuntimeError('VoiceStudio sta già generando audio per Strata.')
        try:
            self._ready()
            body = {'model': 'tts-1', 'input': text, 'voice': voice, 'response_format': 'wav'}
            if 'speed' in payload:body['speed']=speed
            if instructions:body['instructions']=instructions
            if language: body['language'] = language
            raw, _, content_type = self._request('/v1/audio/speech', body, timeout=300, limit=20*1024*1024)
            if not content_type.split(';')[0].strip() in ('audio/wav', 'audio/x-wav') or len(raw)<12 or raw[:4] != b'RIFF' or raw[8:12] != b'WAVE':
                raise RuntimeError('VoiceStudio non ha restituito un file WAV valido.')
            return {'ok': True, 'audio_base64': base64.b64encode(raw).decode('ascii'), 'mime': 'audio/wav', 'bytes': len(raw), 'engine': 'VoiceStudio', 'inference_verified': True}
        finally: self._busy.release()
