"""Agent harness beside Strata.

An external agent harness (OpenCode, or DeepSeek Harness) runs as an *owned* child of
this server, fed by Strata's own model (`/v1/chat/completions`) and by the same MCP
servers the chat page uses. Strata stays the single source of truth: engine, GPU, MCP,
benchmarks. The harness adds orchestration (tools, edits, sessions); it replaces nothing.

Two rules, both inherited from `serve/optional_backends.py`:

* only the child this module started is ever stopped (`serve/process_lifecycle`), and
* the GPU lease (`serve/gpu_lease`) is held for the whole run, so the harness, the
  benchmark and the optional backend take turns instead of colliding.

The module writes its own OpenCode config, translated from Strata's
`data/mcp-dashboard.json`, into `data/agent-harness/`, so the user's global
`~/.config/opencode/` is never touched.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from serve.gpu_lease import GpuLease

OPENCODE_KIND = "opencode"
DSH_KIND = "dsh"
TRUEFORGE_KIND = "trueforge"
HERMES_KIND="hermes"

OWNER = "agent-harness"
DEFAULT_PORT = 4096
DEFAULT_DSH_PORT = 3080
DSH_PACKAGE = "@deepseek-ai/dsh@0.2.0-rc.2"
READY_TIMEOUT_S = 45.0
LOG_TAIL_LINES = 40
DSH_READY_TIMEOUT_S = 180.0       # npx installs the package on first run; give it room

# The URL each harness prints when it is listening. DeepSeek Harness prints it with its
# access token (`.../?token=...`), which is how its own UI authenticates.
URL_PATTERNS = {
    OPENCODE_KIND: re.compile(r"https?://127\.0\.0\.1:\d+/?\b"),
    DSH_KIND: re.compile(r"https?://127\.0\.0\.1:\d+/\?token=[A-Za-z0-9_\-]+"),
}


def translate_mcp(servers: dict) -> dict:
    """Strata's `mcpServers` shape -> OpenCode's `mcp` shape.

    A server is reproduced exactly as declared: a stdio server becomes `local` with the
    command and its arguments joined, an http(s) server becomes `remote`. An entry that
    is neither is skipped rather than guessed: a wrong guess would silently drop tools.
    """
    out: dict = {}
    if not isinstance(servers, dict):
        return out
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url")
        command = cfg.get("command")
        if isinstance(url, str) and url:
            out[name] = {"type": "remote", "url": url, "enabled": True}
            if isinstance(cfg.get('headers'),dict):out[name]['headers']={str(k):str(v) for k,v in cfg['headers'].items()}
        elif isinstance(command, str) and command:
            args = cfg.get("args") or []
            if not isinstance(args, list):
                args = [str(args)]
            out[name] = {"type": "local", "command": [command, *[str(a) for a in args]], "enabled": True}
            if isinstance(cfg.get('env'),dict):out[name]['environment']={str(k):str(v) for k,v in cfg['env'].items()}
    return out


def build_config(mcp_servers: dict, *, base_url: str, model_id: str, model_name: str,
                 context: int, output: int) -> dict:
    """The `opencode.json` for Strata as the model, its MCP servers as the tools.

    `tool_call` and `reasoning` are declared explicitly: without `tool_call` OpenCode does
    not offer tools to the model, which would make the harness useless. `output` is kept
    well under `context` because Strata refuses a request whose prompt plus max_tokens
    runs past the context (400), it does not truncate (docs/DETAILS.md).
    """
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "strata": {
                "name": "Strata (locale)",
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": base_url, "apiKey": os.environ.get("STRATA_API_KEY", "none")},
                "models": {
                    model_id: {
                        "name": model_name,
                        "limit": {"context": int(context), "output": int(output)},
                        "tool_call": True,
                        "reasoning": True,
                    }
                },
            }
        },
        "mcp": translate_mcp(mcp_servers),
        "model": f"hydra/{model_id}",
        # A single local slot cannot run background title generation alongside
        # the actual agent turn. Keep titles manual rather than failing the turn.
        "agent": {"title": {"disable": True}},
    }


def _dsh_plugin_entry(server_name: str, cfg: dict) -> dict | None:
    """One `dsh-mcp-client` plugin entry for a Strata MCP server declaration."""
    if not isinstance(cfg, dict):
        return None
    url = cfg.get("url")
    command = cfg.get("command")
    config: dict = {"serverName": server_name}
    if isinstance(url, str) and url:
        config.update(transport="streamable-http", url=url)
    elif isinstance(command, str) and command:
        args = cfg.get("args") or []
        if not isinstance(args, list):
            args = [str(args)]
        config.update(transport="stdio", command=command, args=[str(a) for a in args])
        if isinstance(cfg.get("cwd"), str):
            config["cwd"] = cfg["cwd"]
    else:
        return None
    if isinstance(cfg.get('env'),dict):config['env']={str(k):str(v) for k,v in cfg['env'].items()}
    if isinstance(cfg.get('headers'),dict):config['headers']={str(k):str(v) for k,v in cfg['headers'].items()}
    return {"id": f"mcp-{server_name}", "name": "@deepseek-ai/dsh-mcp-client", "config": config}


def build_dsh_patch(mcp_servers: dict, *, base_url: str, model_id: str, model_name: str,
                    context: int, output: int) -> list:
    """The `cordis.patch.yml` for DeepSeek Harness: Strata as the model, its MCP servers as tools.

    A profile patch is a list of plugin entries layered over the shipped `web` profile. The
    provider goes through `llm-pi-ai` (OpenAI Chat Completions); `compat` turns off the
    `developer` role and sends `max_tokens` instead of `max_completion_tokens`, both of which
    a llama.cpp-style server refuses. Each MCP server is its own `dsh-mcp-client` entry,
    additive, so nothing shipped is replaced.
    """
    patch: list = [{
        "id": "llm-pi-ai",
        "config": {
            "providers": {
                "strata": {
                    "apiKeyEnv": "STRATA_API_KEY",
                    "api": "openai-completions",
                    "baseURL": base_url,
                    "compat": {"supportsDeveloperRole": False, "maxTokensField": "max_tokens"},
                    "models": [{
                        "id": model_id,
                        "name": model_name,
                        "contextWindow": int(context),
                        "maxOutputTokens": int(output),
                    }],
                }
            }
        },
    },{'id':'agent-default-model','config':{'provider':'strata','model':model_id}},
      # Native background title inference would compete with the one model slot.
      {'id':'session-title-llm','disabled':True}]
    for name, cfg in (mcp_servers or {}).items():
        entry = _dsh_plugin_entry(str(name), cfg)
        if entry is not None:
            patch.append(entry)
    return patch


def hidden_startup_info():
    if os.name!='nt':return None
    info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=subprocess.SW_HIDE
    return info


def _default_binary(kind: str) -> str | None:
    """The harness executable, if it can be found. No download happens here."""
    if kind == OPENCODE_KIND:
        candidate = Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe"
        return str(candidate) if candidate.is_file() else shutil.which("opencode")
    if kind==HERMES_KIND:
        from serve.hermes_integration import runtime
        found=runtime()
        return str(found['python']) if found else None
    if kind == TRUEFORGE_KIND:
        candidate=Path(__file__).resolve().parents[1]/'output/tools/trueforge/node_modules/@truefoundry/trueforge/dist/cli.js'
        return str(candidate) if candidate.is_file() else None
    if kind == DSH_KIND:
        cached=Path(os.environ.get("LOCALAPPDATA",""))/"npm-cache"/"_npx"
        for candidate in sorted(cached.glob("*/node_modules/@deepseek-ai/dsh/lib/bin.js")):
            try:
                package=json.loads((candidate.parent.parent/'package.json').read_text(encoding='utf-8'))
                if package.get('name')=='@deepseek-ai/dsh' and package.get('version')==DSH_PACKAGE.split('@')[-1]:return str(candidate)
            except (OSError,ValueError):continue
        found = shutil.which("dsh")
        if found:
            return found
        return None
    return None


class AgentHarness:
    """Lifecycle of one harness child. One instance, one process, one GPU lease."""

    def __init__(self, root, *, kind: str = OPENCODE_KIND, port: int | None = None,
                 binary: str | None = None, command: list[str] | None = None,
                 health_url: str | None = None, cors_origin: str | None = None,
                 config_dir: Path | None = None, mcp_servers: dict | None = None,
                 base_url: str = "http://127.0.0.1:8080/v1", model_id: str = "strata",
                 model_name: str = "Strata (modello locale)", model_context: int = 131072,
                 model_output: int = 16384, password_env: str | None = None, api_key: str | None = None):
        self.root = Path(root)
        self.kind = kind
        self.port = int(port if port is not None else (9120 if kind==HERMES_KIND else 8790 if kind==TRUEFORGE_KIND else DEFAULT_DSH_PORT if kind == DSH_KIND else DEFAULT_PORT))
        from serve.harness_updates import selected
        active=selected(self.root,kind)
        self.binary = binary or (active['binary'] if active else _default_binary(kind))
        self._command = command
        self.health_url = health_url or (f'http://127.0.0.1:{self.port}/healthz' if kind==TRUEFORGE_KIND else f'http://127.0.0.1:{self.port}/' if kind==HERMES_KIND else None)
        self.cors_origin = cors_origin
        self.config_dir = Path(config_dir) if config_dir else self.root / "data" / "agent-harness"
        self.base_url = base_url
        self.mcp_servers = mcp_servers if mcp_servers is not None else self._load_mcp()
        self.base_url = base_url
        self.api_key = api_key if api_key is not None else os.environ.get("STRATA_API_KEY", "none")
        self.model_id = model_id
        self.model_name = model_name
        self.model_context = model_context
        self.model_output = model_output
        self.password_env = password_env
        # OpenCode v2 always gates its API behind HTTP basic auth (WWW-Authenticate on
        # every /api/* call). Without a password the server is unusable, so one is
        # always set: the caller's own if `password_env` names a variable with a value,
        # otherwise a generated one the Harness panel shows so the browser can be told.
        self.password = (os.environ.get(password_env, "") if password_env else "") or secrets.token_urlsafe(18)
        self.lock = threading.RLock()
        self.child: subprocess.Popen | None = None
        self.lease: GpuLease | None = None
        self._log_handle = None
        self.log_path = self.root / "data" / f"agent-harness-{kind}.log"
        self.state = {"status": "idle", "error": None}
        self._url: str | None = None
        self.idle_stop_s = float(os.environ.get("STRATA_HARNESS_IDLE_STOP", "0") or 0)
        self.started_at: float | None = None
        self.last_activity: float | None = None

    # ---- idle release -------------------------------------------------------
    def idle_should_stop(self, now=None, busy=None):
        """True only when this harness ran unattended long enough to release its RAM.

        Sessions live in data/<kind>-home on disk, so stopping the process loses no
        conversation; the harness is simply started again from the same home. A harness
        with an open session, one that is still starting, or one whose activity cannot be
        read is never stopped by this rule.
        """
        if not self.idle_stop_s:
            return False
        with self.lock:
            status = self.state.get("status")
            child = self.child
            last = self.last_activity
        if status != "ready" or child is None or child.poll() is not None:
            return False
        if busy is None:
            try:
                from serve.harness_activity import activity
                busy = bool(activity(self).get("busy"))
            except Exception:
                return False
        if busy:
            return False
        if last is None:
            return False
        return (now if now is not None else time.monotonic()) - last >= self.idle_stop_s

    def _note_activity(self):
        with self.lock:
            self.last_activity = time.monotonic()

    # ---- inputs -------------------------------------------------------------

    def _load_mcp(self) -> dict:
        for candidate in (self.root / "data" / "mcp-dashboard.json", self.root / "data" / "mcp.json"):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            servers = data.get("mcpServers") or data.get("mcp_servers") or data
            if isinstance(servers, dict):
                from serve.trueforge_setup import bridge_token
                for name in ('browser','memory'):
                    if name in servers:servers[name]={'url':self.base_url.removesuffix('/v1')+'/harness/'+name+'-mcp','headers':{'Authorization':'Bearer '+bridge_token(self.root)}}
                return servers
        return {}

    def config_path(self) -> Path:
        if self.kind==HERMES_KIND:return self.home()/'config.yaml'
        if self.kind == TRUEFORGE_KIND:return self.home()/'integration.json'
        if self.kind == DSH_KIND:
            return self.home() / "profiles" / "web" / "cordis.patch.yml"
        return self.config_dir / "opencode.json"

    def home(self) -> Path:
        """This harness's own home (DSH_HOME for dsh; not used by OpenCode)."""
        return self.root / "data" / f"{self.kind}-home"

    def write_config(self) -> Path | None:
        """Write the harness config: `opencode.json`, or the dsh profile patch."""
        if self.kind==HERMES_KIND:
            from serve.hermes_integration import write_config
            return write_config(self)
        if self.kind==TRUEFORGE_KIND:
            self.home().mkdir(parents=True,exist_ok=True)
            self.config_path().write_text(json.dumps({'model_endpoint':self.base_url,'model':self.model_id,'context':self.model_context,'mcp_bridge':self.base_url.removesuffix('/v1')+'/harness/mcp'}))
            return self.config_path()
        if self.kind == OPENCODE_KIND:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            cfg = build_config(self.mcp_servers, base_url=self.base_url, model_id=self.model_id,
                               model_name=self.model_name, context=self.model_context,
                               output=self.model_output)
            cfg["provider"]["strata"]["options"]["apiKey"] = self.api_key or "none"
            self.config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            return self.config_path()
        if self.kind == DSH_KIND:
            import yaml
            patch = build_dsh_patch(self.mcp_servers, base_url=self.base_url, model_id=self.model_id,
                                    model_name=self.model_name, context=self.model_context,
                                    output=self.model_output)
            # A Cordis patch with a new id only modifies an existing plugin and
            # silently skips absent ids. New MCP clients require explicit insert.
            clients = [entry for entry in patch if entry.get('name') == '@deepseek-ai/dsh-mcp-client']
            patch = [entry for entry in patch if entry not in clients]
            if clients:
                patch.append({'insert': clients})
            path = self.config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(patch, allow_unicode=True, sort_keys=False), encoding="utf-8")
            return path
        return None

    def command(self) -> list[str]:
        if self._command is not None:
            return list(self._command)
        if self.kind==HERMES_KIND:
            from serve.hermes_integration import runtime
            found=runtime(self.root)
            if not found:raise RuntimeError('Runtime Hermes ufficiale non disponibile')
            # Native CLI module argv survives upstream PM dependency re-exec. A nested
            # `-c` through _venv_entry confuses its raw orig_argv reconstruction.
            return [self.binary,'-I','-S',str(found['source']/'pm/_venv_entry.py'),str(found['site']),
                    '-m','hermes_cli.main','dashboard','--host','127.0.0.1','--port',str(self.port),
                    '--no-open','--skip-build','--isolated']
        if self.kind==TRUEFORGE_KIND:
            if not self.binary or not Path(self.binary).is_file():raise RuntimeError('Installa TrueForge ufficiale prima dell’avvio')
            return [shutil.which('node') or 'node',self.binary,'--port',str(self.port)]
        if self.kind == DSH_KIND:
            if self.binary:
                base = [shutil.which('node') or 'node',self.binary] if Path(self.binary).suffix=='.js' else [self.binary]
            else:
                # on Windows npx is npx.cmd: Popen without a shell does not resolve it
                npx = shutil.which("npx") or shutil.which("npx.cmd") or "npx"
                base = [npx, "--yes", DSH_PACKAGE]
            return [*base, "web", "--no-open", "--port", str(self.port)]
        if not self.binary or not Path(self.binary).is_file():
            raise RuntimeError(
                f"il binario di {self.kind} non è installato; installalo e riprova")
        args = ["serve", "--hostname", "127.0.0.1", "--port", str(self.port)]
        if self.cors_origin:
            args += ["--cors", self.cors_origin]
        return [self.binary, *args]

    def environment(self, *, hermes_runtime=None) -> dict:
        """A clean, isolated environment for the child.

        Two hazards, both observed on a real machine:

        * A parent OpenCode session exports its own `OPENCODE_*` variables - a server
          password, a client tag, the embedded-UI switch, experimental flags. Inheriting
          them hands the harness the parent's credentials (and could turn its own UI off).
          They are stripped here; only what this module decides is set.

        * `XDG_STATE_HOME` / `XDG_DATA_HOME` / `XDG_CACHE_HOME` / `XDG_CONFIG_HOME` may
          point at *another* OpenCode's store. On the probe machine they pointed at the
          desktop app, whose session database is tens of gigabytes: the child blocked on
          it and its API died. Every XDG root is redirected into a per-harness sandbox
          under `data/`, so the harness has its own empty store.
        """
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENCODE_")}
        sandbox = self.root / "data" / f"{self.kind}-home"
        for part in ("state", "data", "cache", "config"):
            (sandbox / part).mkdir(parents=True, exist_ok=True)
        env.update({
            "XDG_STATE_HOME": str(sandbox / "state"),
            "XDG_DATA_HOME": str(sandbox / "data"),
            "XDG_CACHE_HOME": str(sandbox / "cache"),
            "XDG_CONFIG_HOME": str(sandbox / "config"),
            "OPENCODE_CONFIG_DIR": str(self.config_dir),
            "OPENCODE_SERVER_PASSWORD": self.password,
            "DSH_HOME": str(self.home()),
            "STRATA_API_KEY": self.api_key or "none",
        })
        if self.kind==HERMES_KIND:
            from serve.hermes_integration import runtime
            found=hermes_runtime or runtime(self.root)
            if not found:raise ValueError('Hermes runtime unavailable')
            env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None);env.update(VIRTUAL_ENV=str(found['venv']),HERMES_HOME=str(self.home()),OPENAI_API_KEY=env['STRATA_API_KEY'],OPENAI_BASE_URL=self.base_url,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',HERMES_WEB_DIST=str(found['source']/'hermes_cli/web_dist'))
        if self.kind==TRUEFORGE_KIND:
            env.update(HOST='127.0.0.1',PORT=str(self.port),STANDALONE='true',SQLITE_PATH=str(self.home()/'db.sqlite'),LOCALAPPDATA=str(self.home()/'appdata'),SENTRY_ENABLED='false',OUTBOUND_URL_ALLOWED_HOSTS='["127.0.0.1","localhost"]',LOCAL_SANDBOX_ROOT_PARENT=str(self.home()/'sandboxes'))
        return env

    # ---- lifecycle ----------------------------------------------------------

    def start(self):
        with self.lock:
            if self.child is not None and self.child.poll() is None:
                raise RuntimeError("un harness è già in esecuzione")
            # the lease first: a second harness, the benchmark or the optional backend must
            # collide here, before anything is spawned or written.
            # Graphical orchestrators own no model weights; the backend owns GPU admission.
            # Holding a GPU reservation here prevents the other UI and optional models.
            self.lease = None
            self.started_at = time.monotonic()
            self.last_activity = time.monotonic()
            self.state.update(status="starting", error=None)
            try:
                self.write_config()
                command = self.command()
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                # truncate: a stale "listening" line from a previous run must not be read as ready
                log = self._log_handle = open(self.log_path, "wb")
                self.child = subprocess.Popen(
                    command, cwd=str(self.root), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    env=self.environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), startupinfo=hidden_startup_info())
                from serve.winjob import contain
                contain(self.child)
                self._await_ready()
                if self.kind==TRUEFORGE_KIND:
                    from serve.trueforge_setup import configure
                    configure(self)
            except Exception as error:
                self._stop_child()
                self._release()
                self.state.update(status="error", error=str(error))
                raise
            return self.status()

    def _await_ready(self):
        """Ready when the child prints its listening URL (or answers a health probe).

        Reading the URL from the log is how the token of DeepSeek Harness is captured:
        its UI is addressed as `.../?token=...`, so without it the embedded chat is 401.
        """
        limit = DSH_READY_TIMEOUT_S if self.kind == DSH_KIND else READY_TIMEOUT_S
        # A caller-injected command (a test stand-in) prints no listening line: trust its
        # health URL, or report ready at once when it has none.
        pattern = URL_PATTERNS.get(self.kind) if self._command is None else None
        if self._command is not None and not self.health_url:
            if self.child.poll() is not None:raise RuntimeError('Processo di prova terminato')
            self.state.update(status='ready',error=None);return
        deadline = time.time() + limit
        while time.time() < deadline:
            if self.child.poll() is not None:
                raise RuntimeError(f"{self.kind} è terminato all'avvio: {self.log_tail()}")
            found = pattern.search(self._log_text()) if pattern is not None else None
            if found:
                self._url = found.group(0)
                self.state.update(status="ready", error=None)
                return
            if self.health_url and self._probe():
                self.state.update(status="ready", error=None)
                return
            time.sleep(0.5)
        raise RuntimeError(f"{self.kind} non è pronto entro {limit:.0f} s: {self.log_tail()}")

    def _log_text(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def _probe(self) -> bool:
        if not self.health_url:
            return False
        try:
            with urllib.request.urlopen(self.health_url, timeout=2) as response:
                return 200 <= response.status < 500
        except (urllib.error.URLError, OSError):
            return False

    def _stop_child(self):
        from serve.process_lifecycle import stop_owned_tree
        stop_owned_tree(self.child)
        self.child = None
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except OSError:
                pass
            self._log_handle = None

    def _release(self):
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    def connect(self):
        """Official graphical UI entry, using a one-use pairing code for OpenCode v2."""
        import base64
        with self.lock:
            if self.status()['status']!='ready':raise RuntimeError('Avvia il motore prima di aprire la sua interfaccia')
            if self.kind in (DSH_KIND,TRUEFORGE_KIND,HERMES_KIND):return {'url':self._url or f'http://127.0.0.1:{self.port}/','ui':'official'}
            base=f'http://127.0.0.1:{self.port}'
            authorization=base64.b64encode(('opencode:'+self.password).encode()).decode()
            request=urllib.request.Request(base+'/api/pair',data=b'',headers={'Authorization':'Basic '+authorization})
            with urllib.request.urlopen(request,timeout=10) as response:pair=json.load(response)
            code=pair.get('code')
            if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',code):raise RuntimeError('Il server non ha restituito un collegamento UI valido')
            return {'url':base+'/auth/connect/'+code,'ui':'official'}

    def stop(self):
        with self.lock:
            from serve.harness_activity import activity
            if activity(self)['busy']:
                raise RuntimeError('Agente occupato o attività non verificabile: attendi la fine del lavoro prima di arrestarlo')
            self._stop_child()
            self._release()
            self.state.update(status="idle", error=None)
        return self.status()

    def close(self):
        """Server shutdown: stop only the process this module started."""
        with self.lock:
            from serve.harness_activity import activity
            if activity(self)['busy']:
                return False
            if self.child is not None or self.lease is not None:
                self._stop_child()
                self._release()
            self.state.update(status="idle", error=None)
            return True

    # ---- views --------------------------------------------------------------

    def log_tail(self, lines: int = 6) -> str:
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return " / ".join(content[-lines:])[-600:]

    def status(self) -> dict:
        if self.state.get("status") == "ready":
            self._note_activity()
        with self.lock:
            from serve.harness_activity import activity
            execution = activity(self)
            alive = self.child is not None and self.child.poll() is None
            status = self.state["status"]
            error = self.state["error"]
            if self.child is not None and not alive and status in ("ready", "starting"):
                status, error = "error", error or f"il processo di {self.kind} è terminato"
            return {
                "kind": self.kind,
                **execution,
                "status": status,
                "port": self.port,
                "url": self._url or f"http://127.0.0.1:{self.port}/",
                "user": "opencode",
                "owned_process": alive,
                "pid": self.child.pid if alive else None,
                # dsh runs through npx when no local binary is found, so it is installable on demand
                "installed": bool(self.binary and Path(self.binary).is_file())
                             or self._command is not None
                             or self.kind == DSH_KIND,
                "tools": len(self.mcp_servers),
                "config": str(self.config_path()),
                "error": error,
            }
