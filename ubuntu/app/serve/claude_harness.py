"""Owned Claude Code print-mode runs, isolated sessions and bounded native UI state."""
import collections
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid


def default_runtime(root):
    root = Path(root)
    try:
        manifest = json.loads((root / 'output/claude-release-manifest.json').read_text())
        binary = root / 'output/tools/claude-code' / manifest['version'] / 'claude.exe'
        if binary.is_file():
            return {'binary': str(binary), 'version': manifest['version']}
    except (OSError, ValueError, KeyError):
        pass
    return None


class ClaudeHarness:
    def __init__(self, root, *, base_url='http://127.0.0.1:8090', model_id='strata', binary=None, api_key=None):
        from serve.harness_updates import selected
        self.root = Path(root).resolve()
        self.home = self.root / 'data/claude-home'
        runtime = selected(root, 'claude') or default_runtime(root) or {}
        self.binary = binary or runtime.get('binary')
        self.version = runtime.get('version')
        self.base_url = base_url.removesuffix('/v1').rstrip('/')
        self.api_key = api_key if api_key is not None else os.environ.get('STRATA_API_KEY', 'none')
        self.model = model_id
        self.context_budget = 131072
        self.output_budget = 2048
        self.cwd = self.root
        self.lock = threading.RLock()
        self.run_timeout_seconds = 120
        self.enabled = False
        self.closing = False
        self.busy = False
        self.child = None
        self.events = collections.deque(maxlen=100)
        self.messages = collections.deque(maxlen=40)
        self.error = None
        self.job = {'state': 'idle'}
        self.session_id = str(uuid.uuid4())
        self.resume = False
        try:
            state = json.loads((self.home / 'dashboard-session.json').read_text())
            self.session_id = str(uuid.UUID(state['session_id']))
            self.resume = bool(state.get('resume'))
            self.model = state.get('model') or model_id
            saved_cwd = Path(state.get('cwd') or self.root).resolve()
            if saved_cwd.is_relative_to(self.root) and saved_cwd.is_dir():
                self.cwd = saved_cwd
        except (OSError, ValueError, KeyError):
            pass

    def status(self):
        with self.lock:
            terminal=self.terminal.status() if hasattr(self,'terminal') else {}
            interactive=terminal.get('ready',False)
            return dict(kind='claude', native=True, installed=bool(self.binary and Path(self.binary).is_file()),
                        version=self.version, enabled=self.enabled, busy=self.busy or terminal.get('busy',False), activity_known=not interactive or terminal.get('activity_known',False),
                        owned_process=bool(self.child and self.child.poll() is None),
                        status='running' if self.busy else 'ready' if self.enabled else 'idle',
                        session_id=self.session_id, model=self.model, cwd=str(self.cwd), error=self.error,
                        messages=list(self.messages), events=list(self.events), job=dict(self.job))

    def start(self):
        with self.lock:
            if not self.binary or not Path(self.binary).is_file():
                raise ValueError('Claude Code ufficiale non installato')
            if self.closing:
                raise ValueError('Dashboard in chiusura')
            self.enabled = True
            return self.status()

    def connect(self):
        return self.start()

    def stop(self):
        with self.lock:
            if self.busy or (getattr(self,'terminal',None) and self.terminal.status().get('busy')):
                raise ValueError('Attendi la conclusione della richiesta Claude Code')
            self.enabled = False
            return self.status()

    def persist(self):
        from serve.configuration import atomic_json
        atomic_json(self.home / 'dashboard-session.json', dict(session_id=self.session_id, resume=self.resume, model=self.model, cwd=str(self.cwd)))

    def new_session(self):
        with self.lock:
            if self.busy or (getattr(self,'terminal',None) and self.terminal.status().get('busy')):
                raise ValueError('La sessione Claude Code è occupata')
            self.session_id = str(uuid.uuid4())
            self.resume = False
            self.messages.clear()
            self.events.clear()
            self.error = None
            self.job = {'state': 'idle'}
            self.persist()
            return self.status()

    def environment(self):
        env = dict(os.environ)
        for key in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
            env.pop(key, None)
        env.update(CLAUDE_CONFIG_DIR=str(self.home), ANTHROPIC_BASE_URL=self.base_url,
                   ANTHROPIC_AUTH_TOKEN=self.api_key or 'none',
                   ANTHROPIC_MODEL=self.model, ANTHROPIC_SMALL_FAST_MODEL=self.model,
                   ANTHROPIC_DEFAULT_HAIKU_MODEL=self.model, ANTHROPIC_DEFAULT_SONNET_MODEL=self.model,
                   ANTHROPIC_DEFAULT_OPUS_MODEL=self.model,
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', DISABLE_AUTOUPDATER='1', DISABLE_UPDATES='1',
                   CLAUDE_CODE_DISABLE_AUTO_MEMORY='0',
                   CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(self.output_budget),
                   CLAUDE_CODE_MAX_CONTEXT_TOKENS=str(self.context_budget))
        return env

    def command(self, prompt):
        return [self.binary, '-p', prompt, '--output-format', 'stream-json', '--verbose',
                '--include-partial-messages', '--model', self.model, '--strict-mcp-config',
                '--mcp-config', str(self.home / 'mcp.json'),
                '--resume' if self.resume else '--session-id', self.session_id]

    def write_mcp(self):
        from serve.configuration import atomic_json
        from serve.trueforge_setup import bridge_token
        try:
            servers = json.loads((self.root / 'data/mcp-dashboard.json').read_text()).get('mcpServers', {})
        except (OSError, ValueError):
            servers = {}
        servers = {name: dict(cfg) for name, cfg in servers.items() if isinstance(cfg, dict)}
        for name, cfg in servers.items():
            if cfg.get('url'):
                cfg.setdefault('type', 'http')
        # Shared services stay on the dashboard hub: never spawn a second browser profile.
        for name in ('browser', 'memory'):
            if name in servers:
                servers[name] = {'type': 'http', 'url': self.base_url + f'/harness/{name}-mcp',
                                 'headers': {'Authorization': 'Bearer ' + bridge_token(self.root)}}
        atomic_json(self.home / 'mcp.json', {'mcpServers': servers})

    def run(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('Invia un oggetto JSON')
        prompt = payload.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32768:
            raise ValueError('Prompt richiesto, massimo 32768 caratteri')
        cwd = Path(payload.get('cwd') or self.cwd).resolve()
        if not cwd.is_relative_to(self.root) or not cwd.is_dir():
            raise ValueError('La cartella deve appartenere a questo progetto')
        model = payload.get('model') or self.model
        if not isinstance(model, str) or not model or len(model) > 200:
            raise ValueError('Modello non valido')
        with self.lock:
            if self.busy or (getattr(self,'terminal',None) and self.terminal.status().get('busy')):
                raise ValueError('Una richiesta Claude Code è già in corso')
            if not self.enabled:
                raise ValueError('Avvia Claude Code prima di inviare una richiesta')
            if self.resume and cwd != self.cwd:
                raise ValueError('Crea una nuova sessione prima di cambiare cartella')
            self.model, self.cwd = model, cwd
            self.home.mkdir(parents=True, exist_ok=True)
            self.write_mcp()
            self.busy, self.error = True, None
            self.job = {'id': uuid.uuid4().hex, 'state': 'running'}
            self.messages.append({'role': 'user', 'content': prompt})
            threading.Thread(target=self._execute, args=(prompt,), daemon=True).start()
            return self.status()

    def _execute(self, prompt):
        from serve.winjob import contain
        stderr_path = self.home / 'last-run.stderr.log'
        result = None
        timed_out=threading.Event();watchdog=None
        try:
            with stderr_path.open('wb') as err:
                with self.lock:
                    if self.closing:
                        raise RuntimeError('Dashboard in chiusura')
                    process = subprocess.Popen(self.command(prompt), cwd=self.cwd, env=self.environment(),
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.child = process
                contain(process)
                def expire():
                    from serve.process_lifecycle import stop_owned_tree
                    timed_out.set();stop_owned_tree(process)
                watchdog=threading.Timer(self.run_timeout_seconds,expire);watchdog.daemon=True;watchdog.start()
                while True:
                    line = process.stdout.readline(1024 * 1024 + 1)
                    if not line:
                        break
                    if len(line) > 1024 * 1024:
                        raise ValueError('Evento Claude Code oltre il limite')
                    event = json.loads(line)
                    with self.lock:
                        # Cap payload size too: bounded event count alone is insufficient.
                        safe = event if len(json.dumps(event)) <= 65536 else {'type': event.get('type'), 'truncated': True}
                        self.events.append(safe)
                        if event.get('session_id') == self.session_id:
                            self.resume = True
                        if event.get('type') == 'assistant':
                            content = event.get('message', {}).get('content', [])
                            text = ''.join(block.get('text', '') for block in content if block.get('type') == 'text')
                            if text:
                                self.messages.append({'role': 'assistant', 'content': text[:32768]})
                        if event.get('type') == 'result':
                            result = event
                code = process.wait()
                if timed_out.is_set():raise RuntimeError('Claude Code: tempo massimo della richiesta superato; processo gestito arrestato')
                if code or result is None or result.get('is_error'):
                    detail = (result or {}).get('result') or (result or {}).get('errors') or stderr_path.read_text(encoding='utf-8', errors='replace')[-4000:]
                    raise RuntimeError(str(detail or f'Claude Code: uscita {code}, risultato assente'))
                with self.lock:
                    self.job.update(state='completed', exit_code=code)
        except Exception as error:
            with self.lock:
                self.error = str(error)[:4000]
                self.job.update(state='error', exit_code=self.child.poll() if self.child else None)
        finally:
            if watchdog:watchdog.cancel()
            from serve.process_lifecycle import stop_owned_tree
            with self.lock:
                stop_owned_tree(self.child)
                if self.child and self.child.stdout:
                    self.child.stdout.close()
                self.child = None
                self.busy = False
                self.persist()

    def close(self):
        from serve.process_lifecycle import stop_owned_tree
        with self.lock:
            if self.busy or (getattr(self,'terminal',None) and self.terminal.status().get('busy')):
                raise ValueError('Claude Code occupato: chiusura rifiutata')
            self.closing = True
            self.enabled = False
            stop_owned_tree(self.child)
