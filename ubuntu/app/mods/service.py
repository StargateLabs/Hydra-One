"""Strata mods overlay: the custom Service methods for models, resources and vision.

The live line's Control tab (setup/download, switch model, catalogue, VRAM and
context budgets, images on/off) is built on these methods. Upstream 0.2.9's
Service manages models for the Terminal and the app through a different API, and
our routes call ours, so the overlay carries them unchanged.

`install(server_module)` adds them to upstream's Service class and injects the
server globals they use. A method upstream already has is left alone.
"""
from __future__ import annotations

import json
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# server globals the method bodies reference; install() copies them in
SERVER_GLOBALS = ("Vision", "vision_env", "engine_args", "GpuBusy")

METHODS = ('resource_state', 'start_setup', 'catalogue_state', '_catalogue_backend', '_last_catalogue_job', 'catalogue_inspect', 'catalogue_search', 'start_catalogue_fetch', '_catalogue_worker', '_catalogue_register', 'prepared_models', 'start_switch', 'setup_state', 'set_resources', 'set_vision', '_set_vision_locked', 'set_shared')

_SERVER = None
_INSTALLED = None


def install(server_module) -> None:
    """Add the custom methods to upstream's Service (idempotent)."""
    global _SERVER, _INSTALLED
    if _INSTALLED is server_module:
        return
    _SERVER = server_module
    module_globals = globals()
    module_globals["ROOT"] = getattr(server_module, "ROOT", ROOT)
    for name in SERVER_GLOBALS:
        if not hasattr(server_module, name):
            raise AttributeError(f"mods.service: the server module has no {name!r}; the hook contract changed")
        module_globals[name] = getattr(server_module, name)
    server_module.find_mmproj = _find_mmproj
    for name in METHODS:
        # always ours: upstream's set_shared swallows a failed save, ours raises (the
        # Control tab shows the error and keeps the previous values)
        setattr(server_module.Service, name, getattr(ServiceMixin, name))
    if not getattr(server_module.Service.ensure_loaded, "_mods_guarded", False):
        original = server_module.Service.ensure_loaded

        def ensure_loaded(self):
            guard_loaded(self)
            return original(self)

        ensure_loaded._mods_guarded = True
        server_module.Service.ensure_loaded = ensure_loaded
    if not getattr(server_module.Service.prepare, "_mods_graph", False):
        original_prepare = server_module.Service.prepare

        def prepare(self, messages, tools, kwargs, max_new=None, *args, **extra):
            """The live line's HYDRA graph context, before upstream's preparation."""
            if extra.get("graph_context", True) and getattr(self, "hydra_native_state", {}).get("enabled")                     and (getattr(self, "cfg", {}) or {}).get("hydra_graph_inference"):
                try:
                    from serve.hydra_graph import prepare as prepare_graph_context
                    messages = prepare_graph_context(self, messages, tools, kwargs, max_new)
                    self._hydra_graph_hook_error = None
                except Exception as exc:
                    # Optional subsystem/import failure must leave native preparation usable.
                    self._hydra_graph_hook_error = type(exc).__name__[:64]
            extra.pop("graph_context", None)
            return original_prepare(self, messages, tools, kwargs, max_new, *args, **extra)

        prepare._mods_graph = True
        server_module.Service.prepare = prepare
    # the two "one at a time" starters check under the lock, release it, then start the
    # work: two calls could both pass. A per-service guard serializes the whole call.
    for _name, _guard_name in (("start_setup", "_mods_setup_guard"),
                               ("start_catalogue_fetch", "_mods_catalogue_guard")):
        _original = getattr(server_module.Service, _name)
        if getattr(_original, "_mods_serial", False):
            continue

        def _serial(self, *args, __original=_original, __guard=_guard_name, **kwargs):
            guard = getattr(self, __guard, None)
            if guard is None:
                guard = threading.Lock()
                setattr(self, __guard, guard)
            with guard:
                return __original(self, *args, **kwargs)

        _serial._mods_serial = True
        setattr(server_module.Service, _name, _serial)
    if not getattr(server_module.Service.metrics, "_mods_build", False):
        original_metrics = server_module.Service.metrics

        def metrics(self, *args, **kwargs):
            """Upstream reads only the version from BUILD.json; the About page also wants
            backend, platform and ROCm version, which the live line filled from the same file."""
            data = original_metrics(self, *args, **kwargs)
            try:
                engine = data.get("engine")
                if isinstance(engine, dict):
                    build = _build_info(self)
                    for key in ("backend", "platform", "rocm"):
                        if not engine.get(key) and build.get(key):
                            engine[key] = build[key]
            except Exception:
                pass
            try:
                # the Monitor's thermal card reads `power`: upstream's /metrics has no
                # power manager, the live line's did (state + advisory limits)
                telemetry = getattr(self, "telemetry", None)
                snapshot = telemetry.snapshot() if telemetry else {"now": {}}
                hardware_now = snapshot.get("now") or {}
                manager = getattr(self, "power_manager", None)
                if manager is not None:
                    if hardware_now:
                        manager.update(power_w=hardware_now.get("gpu_power", 0.0),
                                       temp_c=hardware_now.get("gpu_temp", 0.0),
                                       speed_tps=(data.get("live") or {}).get("tok_s") or 0.0)
                    state = manager.get_state()
                    data["power"] = {
                        "enforcement": "advisory",
                        "mode": manager.config.mode,
                        "power_w": round(state.power_w, 1) if hardware_now.get("gpu_power") is not None else None,
                        "temp_c": round(state.temp_c, 1) if hardware_now.get("gpu_temp") is not None else None,
                        "speed_tps": round(state.speed_tps, 1),
                        "efficiency": round(state.efficiency, 2) if hardware_now.get("gpu_power") else None,
                        "throttling": state.throttling,
                        "throttle_reason": state.throttle_reason,
                        "cooldown_s": round(state.cooldown_s, 1),
                        "temp_limit": manager.config.temp_limit(),
                        "power_limit": manager.config.power_limit(),
                    }
                data["efficiency_sample"] = snapshot.get("efficiency_sample")
            except Exception:
                pass
            try:
                # upstream's /metrics has no benchmark snapshot; the Monitor reads it to
                # switch the tab to the isolated benchmark's own numbers
                from serve.benchmark_monitor import snapshot
                data["benchmark"] = snapshot()
            except Exception:
                pass
            return data

        metrics._mods_build = True
        server_module.Service.metrics = metrics
    _INSTALLED = server_module


def _cat_job_snapshot(svc) -> dict:
    """A catalogue job copy that survives the worker's concurrent dict.update."""
    for _ in range(50):
        try:
            return dict(getattr(svc, "cat_job", {}) or svc._last_catalogue_job())
        except RuntimeError:
            time.sleep(0)
    return {}


def _build_info(svc) -> dict:
    """The BUILD.json beside the configured engine executable (version, backend, platform, rocm)."""
    exe = (getattr(svc, "cfg", {}) or {}).get("exe") or getattr(getattr(svc, "engine", None), "exe", None)
    if not exe:
        return {}
    try:
        return json.loads((Path(exe).parent / "BUILD.json").read_text(encoding="utf-8-sig")) or {}
    except (OSError, ValueError):
        return {}


def guard_loaded(svc) -> None:
    """The live line's checks before the engine starts: a local operation owns the
    GPU, a model switch or a benchmark is running (GpuBusy), AirLLM is preparing."""
    if getattr(svc, "airllm_setup", None) and svc.airllm_setup.job["state"] == "preparing":
        raise RuntimeError("Attendi la preparazione AirLLM prima di avviare il motore")
    if getattr(svc, "switch_in_progress", False):
        raise GpuBusy("Cambio modello in corso")
    from serve.gpu_lease import reserved, owns_inherited_validation_lease
    if reserved(ROOT) and not owns_inherited_validation_lease(ROOT):
        raise GpuBusy("Risorse riservate a una operazione locale; attendi la conclusione")
    from serve.benchmark_monitor import competing_benchmark
    if getattr(svc, "benchmark_lab", None) and svc.benchmark_lab.active():
        raise GpuBusy("Campagna Benchmark in corso. Attendi la conclusione o arrestala dalla pagina Benchmark.")
    benchmark = competing_benchmark(getattr(svc, "port", None))
    if benchmark:
        raise GpuBusy(f"Benchmark isolato in corso ({benchmark}). Attendi la fine del test prima di caricare il motore.")


class ServiceMixin:

    def resource_state(self) -> dict:
        """GET /config: the resource budgets this server is running with, read from its own config's args."""
        cfg = getattr(self, "cfg", None) or {}
        args = list(cfg.get("args") or [])

        def get(flag, default=None):
            if flag in args:
                i = args.index(flag)
                if i + 1 < len(args):
                    try:
                        return int(args[i + 1])
                    except (TypeError, ValueError):
                        return default
            return default

        out = {"vram_reserve_mib": get("--vram-reserve-mib", 0), "kv_resident": get("--kv-resident"),
               "max_context": get("--max-context") or self.engine.max_context,
               "config": getattr(self, "cfg_path", None)}
        try:
            import shutil as _sh
            out["disk_free_gib"] = round(_sh.disk_usage(str(ROOT)).free / 2**30, 1)
        except OSError:
            pass
        return out

    def start_setup(self, model: str) -> dict:
        """POST /setup-download: run the official setup.py for this model in the background (it downloads the
        GGUF shards, prepares the pack and writes run-<model>.bat; --no-start leaves the running server alone).

        One at a time: a second call while one runs returns its state instead of starting another (the download
        is tens of GB and setup itself refuses to run twice)."""
        with self.status_lock:
            run = getattr(self, "_setup", None)
            if run and run.get("proc") and run["proc"].poll() is None:
                return {"status": "running", "model": run["model"], "log": run["log"],
                        "note": "a download is already running"}
        import subprocess
        setup = ROOT / "setup.py"
        if not setup.exists():
            raise ValueError(f"setup.py not found in {ROOT}")
        log = ROOT / f"setup-{model}.log"
        cmd = [sys.executable, str(setup), "--model", model, "--no-start", "--yes"]
        try:
            with open(log, "ab") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} setup.py {' '.join(cmd[2:])}\n".encode())
                proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=fh, stderr=subprocess.STDOUT)
        except OSError as e:
            raise ValueError(f"could not start setup.py: {e}")
        with self.status_lock:
            self._setup = {"proc": proc, "model": model, "log": str(log), "started": time.time()}
        print(f"[strata] setup.py {model} started (pid {proc.pid}), log: {log}", flush=True)
        return {"status": "started", "model": model, "pid": proc.pid, "log": str(log)}

    def _catalogue_backend(self) -> str:
        """The engine the catalogue must describe.

        The phase-1 dashboard is only a mock shell, but the same installation
        contains the native CUDA engine and its models.  Without a run config
        the backend used to read "unknown" and the whole native catalogue was
        hidden; fall back to the installed native binary instead.
        """
        backend=str((getattr(self,'cfg',{}) or {}).get('backend') or '').lower()
        if backend:
            return backend
        root=Path(__file__).resolve().parents[1]
        if (root/'engine/strata').is_file() or (root/'engine/strata.exe').is_file():
            return 'cuda'
        return 'unknown'

    def catalogue_state(self) -> dict:
        from serve import catalogue as cat
        from serve.catalogue_verified import fit_host
        host=cat.host();backend=self._catalogue_backend()
        entries=[]
        for entry in getattr(self,'cat_entries',[]):
            if fit_host(entry['quant'],entry['download_gib'],host,backend,entry['on_disk'])[0]:
                entries.append({**entry,'fit':{**entry['fit'],'host':host}})
        return {'entries':entries,'official':[],'job':_cat_job_snapshot(self),
                'host':host,'backend':backend,'prepared':self.prepared_models(),
                'disk':{'free_gib':host['free_gib']},'checked_at':getattr(self,'cat_checked_at',None)}

    def _last_catalogue_job(self):
        try:return json.loads((ROOT/'data/catalogue-last-job.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}

    def catalogue_inspect(self,repo: str,quant: str=None) -> dict:
        from serve import catalogue as cat
        from serve import catalogue_verified as verified
        if quant is None:
            groups=verified.repo_info(repo)['groups']
            quant=next((q for q in ('IQ3_XXS','IQ2_XS','Q2_0','IQ3_S','IQ1_M') if q in groups),None)
        if not quant:raise ValueError('Nessuna quantizzazione supportata')
        return verified.inspect(repo,quant,cat.host(),self._catalogue_backend(),ROOT)

    def catalogue_search(self,query: str) -> dict:
        from serve import catalogue as cat
        from serve import catalogue_verified as verified
        result=verified.search(query,cat.host(),self._catalogue_backend(),ROOT)
        self.cat_entries=result['results'];self.cat_checked_at=result['checked_at']
        return result

    def start_catalogue_fetch(self,repo: str,quant: str,key: str=None,mtp: bool=False) -> dict:
        from serve import catalogue as cat
        if mtp:raise ValueError('Le teste MTP separate non sono validate in questo flusso; nessun download avviato')
        # A catalogue download only uses disk and network: a model already
        # loaded on the GPU must not block it.
        if self.benchmark_lab.active():raise ValueError('Attendi la fine della campagna Benchmark')
        with self.status_lock:
            if getattr(self,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):
                raise ValueError('Una preparazione è già in corso')
            self.cat_job={'state':'starting','repo':repo,'quant':quant,'started':time.time()}
        try:
            info=self.catalogue_inspect(repo,quant)
            chiave=key or info['key']
            if not re.fullmatch(r'[a-z0-9_]{1,32}',chiave):raise ValueError('Identificatore del modello non valido')
            if (ROOT/f'strata-{chiave}.json').exists():raise ValueError('Configurazione già presente; non viene sovrascritta')
            pack=cat.DATA/'packs'/chiave
            if pack.exists():raise ValueError('Pack già presente; non viene sovrascritto')
            self.cat_job.update(key=chiave,revision=info['revision'],files=info['files'],inspection=info,
                                download_gib=info['download_gib'],download_bytes=info['download_bytes'],log=str(ROOT/f'strata-catalogo-{chiave}.log'))
            threading.Thread(target=self._catalogue_worker,args=(repo,quant,chiave,False),daemon=True).start()
            return dict(self.cat_job)
        except Exception as exc:
            self.cat_job.update(state='failed',error=str(exc));raise

    def _catalogue_worker(self,repo: str,quant: str,chiave: str,mtp: bool=False) -> None:
        from serve import catalogue as cat
        from serve.configuration import atomic_json
        log=Path(self.cat_job['log']);files=list(self.cat_job['files']);revision=self.cat_job['revision']
        try:
            self.cat_job.update(state='downloading',step=1)
            dest=cat.DATA/'models'/chiave;dest.mkdir(parents=True,exist_ok=True)
            from huggingface_hub import snapshot_download
            from serve.download_progress import DownloadProgress
            expected=int(self.cat_job['download_bytes'])
            def publish_progress(progress):self.cat_job['progress']=progress
            cached=sum(f['bytes'] for f in self.cat_job['inspection'].get('file_metadata',[]) if (dest/f['path']).is_file() and (dest/f['path']).stat().st_size==f['bytes'])
            tracker=DownloadProgress(expected,publish_progress,cached=cached)
            snapshot_download(repo_id=repo,revision=revision,allow_patterns=files,local_dir=str(dest),max_workers=4,tqdm_class=tracker.progress_class())
            tracker.finish()
            self.cat_job.update(state='verifying',verification=dict(files_total=len(files),verified_files=0))
            for item in self.cat_job['inspection']['file_metadata']:
                with (dest/item['path']).open('rb') as source:
                    actual=hashlib.file_digest(source,'sha256').hexdigest()
                if actual!=item['sha256']:raise ValueError('Verifica SHA256 fallita: '+item['path'])
                self.cat_job['verification']['verified_files']+=1

            self.cat_job.update(state='packing',step=2)
            first=next((f for f in files if re.search(r'-00001-of-\d{5}\.gguf$',f)),files[0])
            final=cat.DATA/'packs'/chiave;staging=cat.DATA/'packs'/('.'+chiave+'-'+uuid.uuid4().hex[:8])
            command=[sys.executable,str(ROOT/'tools/iq_pack.py'),'--gguf',str(dest/first),'--out',str(staging),'--compat-bf16']
            with log.open('ab') as output:subprocess.run(command,cwd=str(ROOT),stdout=output,stderr=subprocess.STDOUT,check=True)
            if final.exists():raise ValueError('Pack creato da un altro lavoro; non viene sovrascritto')
            staging.rename(final)
            self.cat_job.update(state='registering',step=3)
            config=self._catalogue_register(chiave,dest,files)
            self.cat_job.update(state='done',step=3,config=config,pack=str(final))
            atomic_json(ROOT/'data/catalogue-last-job.json',dict(self.cat_job))
        except Exception as exc:self.cat_job.update(state='failed',error=str(exc))

    def _catalogue_register(self,chiave: str,dest: pathlib.Path,files: list) -> str:
        from serve.model_inventory import inspect_config
        from gguf_reader import GGUFFile
        from make_profile import read_profile,write_profile
        model=json.loads((ROOT/'strata-iq3_xxs.json').read_text(encoding='utf-8-sig'))
        args=list(model['args']);shards=sorted(f for f in files if f.lower().endswith('.gguf') and 'mmproj' not in f.lower() and 'mtp/' not in f.lower())
        if not shards:raise ValueError('Shard del modello mancanti')
        first=next((f for f in shards if re.search(r'-00001-of-\d{5}\.gguf$',f)),shards[0])
        ple=next((f for f in shards if GGUFFile(dest/f).find('per_layer_token_embd.weight')),None)
        if ple is None:raise ValueError('Tabella PLE non trovata negli shard')
        def setf(flag,value):
            if flag in args:args[args.index(flag)+1]=str(value)
            else:args.extend([flag,str(value)])
        pack=ROOT.parent/'Strata-data/packs'/chiave
        setf('--pack',pack);setf('--native',dest/first);setf('--ple-gguf',dest/ple)
        experts=self.cat_job['inspection']['experts'];directory=ROOT/'data/catalogue'/chiave;directory.mkdir(parents=True,exist_ok=True)
        base_pairs=read_profile(ROOT/'data/expert-profile.bin')
        pairs=[p for p in base_pairs if p[1]<experts];profile=directory/'expert-profile.bin'
        if profile.exists():raise ValueError('Profilo già presente; non viene sovrascritto')
        write_profile(profile,pairs,n_expert=experts);setf('--expert-profile',profile)
        # A newly downloaded checkpoint must not silently inherit another model's draft or encoder.
        for flag in ('--mtp','--mtp-draft-vocab'):
            if flag in args:i=args.index(flag);del args[i:i+2]
        model.pop('vision',None);model.pop('expert_profile_save',None)
        model.update(args=args,tokenizer=str(pack/'tokenizer'),model_name='qwen3.8-flash-next-'+chiave,log=str(ROOT/f'strata-{chiave}.log'))
        inspection=self.cat_job['inspection']
        model['catalogue']={k:inspection.get(k) for k in ('repo','quant','author','revision','download_gib','layout')}
        model['display_name']=('Qwen3.8 Flash Next Hybrid · IQ3/Q2 · shefowl' if inspection['repo']=='shefowl/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-Hybrid-GGUF' else inspection['title']+' · '+inspection['quant']+' · '+inspection['author'])
        model.pop('model',None)
        out=ROOT/f'strata-{chiave}.json'
        with out.open('x',encoding='utf-8') as output:json.dump(model,output,ensure_ascii=False,indent=2)
        ready=inspect_config(out)
        if not ready['ready']:raise ValueError('Preparazione incompleta: '+ready['error'])
        return str(out)

    def prepared_models(self) -> list:
        from serve.model_inventory import inventory
        return inventory(ROOT)

    def start_switch(self, model: str) -> dict:
        """POST /switch-model: passa a un'altra configurazione GIA' PREPARATA, sulla stessa porta.

        Il modello in uso e' deciso dalla configurazione con cui il server e' partito, quindi cambiarlo
        vuol dire riavviare il server con un'altra configurazione. Il server attuale tiene la porta:
        percio' lancia un aiutante che aspetta che si liberi e poi avvia l'altro, e subito dopo esce."""
        from serve.model_inventory import inspect_config
        from serve.benchmark_monitor import competing_benchmark
        if self.benchmark_lab.active() or competing_benchmark(getattr(self,'port',None)):
            raise ValueError('Attendi la conclusione del benchmark prima di cambiare modello')
        if getattr(self,'cat_job',{}).get('state') in ('starting','downloading','verifying','packing','registering'):
            raise ValueError('Attendi la preparazione del catalogo')
        disponibili = {}
        for f in sorted(ROOT.glob("strata-*.json")):
            if ".bak" in f.name:
                continue
            disponibili[f.stem[len("strata-"):].lower().replace("-", "_")] = f
        chiave = model.strip().lower().replace("-", "_").replace(" ", "_")
        target = disponibili.get(chiave)
        if target is None:
            raise ValueError("nessuna configurazione pronta per %r: usa prima 'Scarica e configura'. "
                             "Pronte adesso: %s" % (model, ", ".join(sorted(disponibili)) or "nessuna"))
        porta = int(getattr(self, "port", 0) or 8090)
        ready=inspect_config(target)
        if not ready['ready']:raise ValueError('Modello non pronto: '+ready['error'])
        target_cfg=json.loads(target.read_text(encoding='utf-8-sig'))
        target_model=target_cfg.get('model_name') or target_cfg.get('model')
        if Path(getattr(self,'cfg_path','') or '.').resolve()==target.resolve():
            return {'status':'already_active','model':chiave,'target_model':target_model}
        if os.environ.get('STRATA_MOCK_SHELL')=='1' and type(self.engine).__name__=='MockEngine':
            raise ValueError('Il motore nativo Strata si avvia con la scorciatoia Qwen3.8 Ubuntu; la dashboard HYDRA non cambia motore da qui.')
        if not self.fifo.acquire(blocking=False):raise ValueError('Attendi la fine della richiesta in corso')
        try:
            self.switch_in_progress=True
            if self.loaded():
                unload=getattr(self.engine,'unload',None)
                if unload is not None:unload()
        except BaseException:
            self.switch_in_progress=False
            raise
        finally:self.fifo.release()
        aiuto = ROOT / "serve" / "_switch.py"
        if not aiuto.exists():
            self.switch_in_progress=False
            raise ValueError("manca serve/_switch.py")
        import subprocess as _sp
        import threading
        flag = 0
        for nome in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
            flag |= getattr(_sp, nome, 0)
        log = ROOT / f"strata-cambio-{chiave}.log"
        try:
            with open(log, "ab") as fh:
                fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} cambio modello richiesto -> {target.name}\n".encode())
                _sp.Popen([sys.executable, str(aiuto), str(target), str(porta), str(ROOT)],
                          cwd=str(ROOT), stdout=fh, stderr=_sp.STDOUT, stdin=_sp.DEVNULL,
                          creationflags=flag, close_fds=True)
        except OSError as e:
            self.switch_in_progress=False
            raise ValueError(f"non riesco ad avviare il cambio: {e}")
        threading.Timer(2.5, lambda: os._exit(0)).start()
        print(f"[strata] cambio modello -> {target.name} sulla porta {porta}; questo server esce", flush=True)
        return {"status": "switching", "model": chiave, "target_model":target_model,"config": str(target), "port": porta,
                "note": "il server si riavvia: la pagina si riconnette da sola fra qualche secondo"}

    def setup_state(self) -> dict:
        """GET /config's setup half: whether a download runs, its model and its log's tail."""
        with self.status_lock:
            run = getattr(self, "_setup", None)
        if not run:
            return {"status": "idle"}
        alive = bool(run.get("proc")) and run["proc"].poll() is None
        tail = ""
        try:
            with open(run["log"], "rb") as f:
                f.seek(max(0, os.fstat(f.fileno()).st_size - 2000))
                tail = f.read().decode("utf-8", "replace").strip().splitlines()[-1][-200:]
        except OSError:
            pass
        return {"status": "running" if alive else "done", "model": run["model"], "log": run["log"], "last": tail}

    def set_resources(self, vram_reserve_mib=None, kv_resident=None, max_context=None, validate_only=False) -> dict:
        """Write resource budgets into this server's config (`args`) and return what changed.

        The values are the engine's own flags, so they apply at the next engine start: --vram-reserve-mib
        (VRAM left to the desktop), --kv-resident (context kept in VRAM: more = faster, less VRAM for experts)
        and --max-context (the window).  Nothing is guessed: an unknown or out-of-range value is refused."""
        cfg = dict(getattr(self, "cfg", None) or {})
        args = list(cfg.get("args") or [])
        changed = {}

        def put(flag, value, low, high):
            nonlocal args                          # += would otherwise make `args` local to this nested function
            if value is None:
                return
            from serve.configuration import whole_number
            n = whole_number(value, flag, low, high)
            if flag in args:                       # replace the flag's current value in place
                i = args.index(flag)
                if i + 1 < len(args):
                    if args[i + 1] != str(n):
                        args[i + 1] = str(n)
                        changed[flag.lstrip("-").replace("-", "_")] = n
                else:
                    args.append(str(n))
                    changed[flag.lstrip("-").replace("-", "_")] = n
            else:
                args.extend([flag, str(n)])
                changed[flag.lstrip("-").replace("-", "_")] = n

        put("--vram-reserve-mib", vram_reserve_mib, 0, 16384)
        put("--kv-resident", kv_resident, 2048, 262144)
        put("--max-context", max_context, 2048, 262144)
        def effective(flag):
            return int(args[args.index(flag) + 1]) if flag in args else None
        kv, ctx = effective("--kv-resident"), effective("--max-context")
        if kv is not None and ctx is not None and kv > ctx:
            raise ValueError("--kv-resident cannot exceed --max-context")
        if validate_only:
            return changed
        if not changed:
            return {}
        cfg["args"] = args
        path = getattr(self, "cfg_path", None)
        if path:
            try:
                from serve.configuration import atomic_json
                atomic_json(path, cfg)
            except OSError as e:
                raise ValueError(f"could not write {path}: {e}")
        self.cfg = cfg
        if hasattr(self.engine, "spawn"):
            exe, _, cwd, log, env = self.engine.spawn
            self.engine.spawn = (exe, _SERVER.engine_args(cfg), cwd, log, env)
        return changed

    def set_vision(self, on) -> dict:
        if on is None:
            return {}
        if not isinstance(on, bool):
            raise ValueError("vision must be true or false")
        if not self.fifo.acquire(blocking=False):
            raise _SERVER.GpuBusy("images cannot be changed while the model is serving a request")
        try:
            return self._set_vision_locked(on)
        finally:
            self.fifo.release()

    def _set_vision_locked(self, on) -> dict:
        """Images on/off: writes this config's `vision` block and starts or stops the encoder now.

        The encoder is built here as at startup. A changed image mode unloads the
        engine, whose next lazy start allocates the correct rotary-position table.
        It stays off unless asked for, because the encoder's
        memory comes on top of the experts already in RAM on a 64 GB PC.
        """
        if on is None:
            return {}
        if not isinstance(on, bool):
            raise ValueError("vision must be true or false")
        cfg = dict(getattr(self, "cfg", None) or {})
        want = bool(on)
        path = getattr(self, "cfg_path", None)

        def write():
            if path:
                try:
                    from serve.configuration import atomic_json
                    atomic_json(path, cfg)
                except OSError as e:
                    raise ValueError(f"could not write {path}: {e}")
            self.cfg = cfg

        args = list(cfg.get("args") or [])
        native = None
        if "--native" in args and args.index("--native") + 1 < len(args):
            native = args[args.index("--native") + 1]

        if want:
            if not native:
                raise ValueError("this config has no --native shard: the image encoder needs it")
            mm = find_mmproj(cfg, native)
            if mm is None:
                raise ValueError("no mmproj file (the model's image projector): images cannot be enabled")
            cwd = Path(cfg.get("cwd") or ".")
            exe = cwd / "engine" / ("strata-vision.exe" if os.name == "nt" else "strata-vision")
            if not exe.exists():
                raise ValueError(f"the image encoder is not installed: {exe}")
            cfg["vision"] = {"exe": str(exe), "mmproj": str(mm), "model": str(native),
                             "gpu": False, "max_tokens": 300,      # setup.py VISION["cpu"]["max_tokens"]
                             "threads": max(1, (os.cpu_count() or 8) // 2)}
            candidate = None
            if self.vision is None:
                log = open(cfg["log"], "a", encoding="utf-8") if cfg.get("log") else None
                try:
                    candidate = _SERVER.Vision(cfg["vision"], log=log, env=_SERVER.vision_env(cfg, dict(os.environ)))
                except (OSError, RuntimeError) as e:
                    if log: log.close()
                    raise ValueError(f"could not enable images: {e}") from e
            try:
                write()
            except Exception:
                if candidate:
                    candidate.unload()
                    if log: log.close()
                raise
            if candidate:
                self.vision = candidate
        else:
            cfg.pop("vision", None)
            cfg["args"] = [a for a in args if a != "--vision"]
            write()
            if self.vision is not None:
                try:
                    self.vision.unload()
                finally:
                    self.vision = None
        if hasattr(self.engine, "spawn"):
            exe, old_args, cwd, log, env = self.engine.spawn
            new_args = _SERVER.engine_args(cfg)
            self.engine.spawn = (exe, new_args, cwd, log, env)
            if ("--vision" in old_args) != ("--vision" in new_args) and self.engine.alive():
                self.engine.unload()
        return {"vision": want}

    def set_shared(self, defaults) -> dict:
        """The Chat settings every client gets for what it leaves out; {} / None = clients use their own again."""
        shared = _SERVER.clean_shared_defaults(defaults)
        if self.shared_path:
            try:
                if shared:
                    from serve.configuration import atomic_json
                    atomic_json(self.shared_path, shared)
                else:
                    Path(self.shared_path).unlink(missing_ok=True)
            except OSError as e:
                raise ValueError(f"could not save shared settings: {e}") from e
        self.shared = shared
        return self.shared


def find_mmproj(cfg, native):
    """The server module's copy: tests patch `serve.server.find_mmproj` and ours must see it."""
    if _SERVER is not None and hasattr(_SERVER, "find_mmproj"):
        return _SERVER.find_mmproj(cfg, native)
    return _find_mmproj(cfg, native)


def _find_mmproj(cfg: dict, native: str | None) -> Path | None:
    """The model's image projector (mmproj-*.gguf), looked for where setup.py puts it.

    setup.py writes it into the models dir; a checkout may also keep it beside the model's shards.
    Returns None rather than guessing a path that does not exist.
    """
    cands: list[Path] = []
    if native:
        cands.append(Path(native).parent)
    base = Path(cfg.get("cwd") or ".")
    cands += [base.parent / "Strata-data" / "models", base / "models", base / "Strata-data" / "models"]
    for d in cands:
        try:
            hit = sorted(Path(d).glob("mmproj-*.gguf"))
        except OSError:
            hit = []
        if hit:
            return hit[0]
    return None
