"""Codex's own interactive TUI inside Hydra's existing ConPTY transport."""
import os
from pathlib import Path
import shutil
import threading
from serve.original_harness_transport import Transport


class CodexTerminal:
    def __init__(self, root):
        self.root = Path(root)
        self.transport = Transport(root)
        self.lock = threading.RLock()
        # User scope is explicit; no arbitrary path accepted from a browser/model.
        from serve.ara_history import workspace
        self.cwd = workspace()

    def binary(self):
        binary = shutil.which('codex.exe')
        if not binary:
            local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
            candidates = [p for p in (local / 'OpenAI' / 'Codex' / 'bin').glob('*/codex.exe') if p.is_file()]
            if candidates:
                binary = str(max(candidates, key=lambda p: p.stat().st_mtime_ns))
        if not binary:
            raise ValueError('Codex.exe originale non trovato nel PATH o installazione ufficiale utente; nessun client sostitutivo avviato')
        return binary

    def installed(self):
        try:
            self.binary()
            return True
        except ValueError:
            return False

    def status(self):
        state = self.transport.snapshot(); state.pop('chunks', None)
        state.update(kind='codex', original_ui=True, interactive=True,
                     installed=self.installed(), status='ready' if state['ready'] else 'idle',
                     activity_known=False, busy=state['ready'], workspace=str(self.cwd),
                     provider='Configurazione nativa Codex', tools=None)
        return state

    def start(self):
        with self.lock:
            if self.transport.snapshot()['ready']: return self.status()
            from serve.ara_history import workspace
            self.cwd=workspace()
            if not self.cwd.is_dir(): raise ValueError('Cartella ARA autorizzata non disponibile')
            # Preserve native provider/auth; never pretend Chat Completions is Responses.
            args = ['--cd', str(self.cwd), '--sandbox', 'workspace-write', '--ask-for-approval', 'on-request',
                    '-c', 'approvals_reviewer="user"', '-c', 'sandbox_workspace_write.network_access=false',
                    '-c', 'sandbox_workspace_write.writable_roots=[]']
            self.transport.start({'mode': 'codex', 'binary': self.binary(), 'args': args,
                                  'cwd': str(self.cwd), 'env': {**os.environ,'TERM':'xterm-256color','COLORTERM':'truecolor'}})
            return self.status()

    def input(self, payload):
        action = payload.get('action')
        if action == 'resize' and set(payload) == {'action', 'cols', 'rows'}:
            if any(type(payload[k]) is not int or not 10 <= payload[k] <= 400 for k in ('cols', 'rows')):
                raise ValueError('Dimensioni terminale non valide')
        elif action == 'input' and set(payload) == {'action', 'data'}:
            if not isinstance(payload['data'], str) or len(payload['data']) > 8192:
                raise ValueError('Input terminale non valido')
        else: raise ValueError('Azione terminale non valida')
        self.transport.send(payload)
        return {'ok': True}

    def resume_message(self, identity, prompt):
        from serve.ara_history import CodexReader,scoped,safe
        import re
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',identity):raise ValueError('Identificatore Codex non valido')
        if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=2000 or safe(prompt)!=prompt:raise ValueError('Messaggio non valido o riservato')
        with self.lock:
            if self.transport.snapshot()['ready']:
                raise ValueError('Codex originale è già aperto in Hydra. Invia da quella interfaccia o esci con /quit prima di riprendere un’altra chat; nessun testo è stato inviato.')
            from serve.ara_history import workspace
            self.cwd=workspace()
            with CodexReader() as client:
                thread=client.request('thread/read',{'threadId':identity,'includeTurns':False})['thread']
                if not scoped(thread.get('cwd')):raise ValueError('Chat fuori dal progetto ARA')
                if thread.get('status',{}).get('type')=='active':raise ValueError('Chat Codex occupata; attendi la conclusione')
                turns=client.request('thread/turns/list',{'threadId':identity,'limit':1,'itemsView':'full','sortDirection':'desc'})
                if any(row.get('status')=='inProgress' for row in turns.get('data',[])):raise ValueError('Turno Codex in corso; nessun invio concorrente')
            args=['resume','--cd',str(self.cwd),'--sandbox','read-only','--ask-for-approval','on-request',
                  '-c','approvals_reviewer="user"','--',identity,prompt.strip()]
            self.transport.start({'mode':'codex','binary':self.binary(),'args':args,'cwd':str(self.cwd),'env':{**os.environ,'TERM':'xterm-256color','COLORTERM':'truecolor'}})
            return {'status':'submitted_to_original_client','thread_id':identity,'completion_verified':False,
                    'original_ui':'http://127.0.0.1:8090/#chat','detail':'Richiesta passata a Codex originale. Risposta e autorizzazioni nella sezione Codex di Hydra; nessun risultato ancora dichiarato.'}

    def close(self, automatic=False):
        # No activity hooks are assumed. Closing a tab must not terminate a task.
        if self.transport.snapshot()['ready']:
            raise ValueError('Esci da Codex con /quit nel terminale originale; nessun compito viene interrotto automaticamente')
        self.transport.close()
        return {'ok': True}


_creation = threading.Lock()


def terminal(svc):
    with _creation:
        if not hasattr(svc, 'codex_original'):
            svc.codex_original = CodexTerminal(svc.update_center.root)
    return svc.codex_original


def route(handler, svc, path, post=False):
    prefix = '/harness/codex/'
    if not path.startswith(prefix): return False
    if not handler._authorized() or not handler._own_page('Codex originale riservato alla dashboard'): return True
    try:
        app = terminal(svc); action = path[len(prefix):]
        if not post:
            if action == 'status': result = app.status()
            elif action == 'terminal':
                from urllib.parse import parse_qs, urlsplit
                after = int(parse_qs(urlsplit(handler.path).query).get('after', ['0'])[0])
                result = {**app.transport.snapshot(after), 'activity_known': False, 'busy': app.status()['busy']}
            else: raise ValueError('Endpoint Codex non disponibile')
        else:
            import json
            if not 0 < int(handler.headers.get('Content-Length', 0)) <= 32768:
                raise ValueError('Richiesta oltre il limite')
            payload = json.loads(handler._read_body())
            if not isinstance(payload, dict): raise ValueError('Richiesta JSON non valida')
            if action == 'terminal/start' and payload == {}: result = app.start()
            elif action == 'terminal/input': result = app.input(payload)
            elif action == 'terminal/stop': result = app.close()
            else: raise ValueError('Azione Codex non disponibile')
        handler._json(200, result)
    except (ValueError, OSError, RuntimeError) as error:
        handler._json(409, {'error': {'message': str(error)}})
    return True
