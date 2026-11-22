"""Bounded owned transport. No reconstructed application UI or public socket."""
import collections
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import sys
import uuid
import re


class Transport:
    def __init__(self, root):
        self.root = Path(root)
        self.child = None
        self.lock = threading.RLock()
        self.ready = threading.Event()
        self.output = collections.deque(maxlen=300)
        self.cursor = 0
        self.frame = None
        self.frame_cursor = 0
        self.viewport = None
        self.error = None
        self.pid = None
        self.last_output = 0
        self.last_used=time.monotonic()
        self.idle_stop=None

    def touch(self):
        self.last_used=time.monotonic()

    def _idle(self,child):
        while self.child is child and child.poll() is None:
            time.sleep(5)
            if self.child is not child:return
            if time.monotonic()-self.last_used>=30 and self.idle_stop:
                try:self.idle_stop()
                except (OSError,ValueError,RuntimeError):pass

    def start(self, payload):
        with self.lock:
            if self.child and self.child.poll() is None:
                return
            node = shutil.which('node')
            if not node:
                raise RuntimeError('Node.js necessario al trasporto originale')
            self.ready.clear(); self.error = None; self.output.clear(); self.cursor = 0
            self.frame=None;self.frame_cursor=0;self.viewport=None;self.pid=None;self.last_output=0
            self.child = subprocess.Popen([node, str(self.root/'tools/harness-native/bridge.cjs')],
                cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            threading.Thread(target=self._read, args=(self.child,), daemon=True).start()
            self.send(payload)
            if self.idle_stop:threading.Thread(target=self._idle,args=(self.child,),daemon=True).start()
        if not self.ready.wait(15) or self.error or self.child.poll() is not None:
            self.close()
            raise RuntimeError(self.error or 'Trasporto originale non pronto')

    def _read(self, child):
        try:
            for line in child.stdout:
                event = json.loads(line)
                with self.lock:
                    if self.child is not child:return
                    if event.get('event') == 'ready':
                        self.pid = event.get('pid'); self.ready.set()
                    elif event.get('event') == 'error':
                        self.error = event.get('error'); self.ready.set()
                    elif event.get('event') == 'output':
                        self.cursor += 1; self.output.append((self.cursor,event['data']))
                        self.last_output=time.monotonic()
                    elif event.get('event') == 'frame':
                        self.frame = event['data']; self.frame_cursor += 1
                        metadata=event.get('metadata') or {}
                        if metadata.get('deviceWidth') and metadata.get('deviceHeight'):
                            self.viewport={'width':metadata['deviceWidth'],'height':metadata['deviceHeight']}
        except (OSError,ValueError) as error:
            with self.lock:
                if self.child is child:self.error = str(error)
        finally:
            with self.lock:
                if self.child is child:self.ready.set()

    def send(self, payload):
        with self.lock:
            if not self.child or self.child.poll() is not None:
                raise RuntimeError('Interfaccia originale chiusa')
            self.child.stdin.write(json.dumps(payload)+'\n'); self.child.stdin.flush()
            self.touch()

    def snapshot(self, after=0):
        if type(after) is not int or after < 0:
            raise ValueError('Cursore non valido')
        with self.lock:
            return {'ready':bool(self.child and self.child.poll() is None and self.ready.is_set() and not self.error),
                    'cursor':self.cursor,'chunks':[data for cursor,data in self.output if cursor>after],
                    'reset':bool(self.output and after and after<self.output[0][0]-1),'error':self.error}

    def close(self):
        with self.lock:
            child=self.child
            if child:
                if child.stdin and not child.stdin.closed:child.stdin.close()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    from serve.process_lifecycle import stop_owned_tree
                    stop_owned_tree(child)
                for stream in (child.stdout,child.stderr):
                    if stream:stream.close()
                self.child=None


class ClaudeTerminal:
    def __init__(self,harness):
        self.harness=harness
        self.transport=Transport(harness.root)
        self.activity_known=False
        self.token=uuid.uuid4().hex
        self.has_draft=False
        self.marker=harness.home/'native-terminal-activity.json'
        self.transport.idle_stop=lambda:self.close(automatic=True)

    def start(self):
        harness=self.harness
        self.transport.touch()
        if self.transport.snapshot()['ready']:return self.status()
        if harness.busy:raise RuntimeError('Claude Code ha una richiesta attiva')
        harness.start();harness.home.mkdir(parents=True,exist_ok=True);harness.write_mcp()
        from serve.configuration import atomic_json
        try:previous=json.loads(self.marker.read_text(encoding='utf-8'));session=str(uuid.UUID(previous.get('session_id')))
        except (OSError,ValueError,TypeError,AttributeError):session=None
        atomic_json(self.marker,{'token':self.token,'busy':True,'known':False,**({'session_id':session} if session else {})})
        hook_command=subprocess.list2cmdline([Path(sys.executable).as_posix(),(harness.root/'tools/claude_terminal_activity.py').as_posix(),self.marker.as_posix(),self.token])
        settings=harness.home/'native-terminal-hooks.json'
        atomic_json(settings,{'hooks':{name:[{'matcher':'idle_prompt' if name=='Notification' else '*','hooks':[{'type':'command','command':hook_command,'timeout':5}]}] for name in ('SessionStart','UserPromptSubmit','PreToolUse','Stop','SessionEnd','Notification')}})
        args=['--model',harness.model,'--strict-mcp-config','--mcp-config',str(harness.home/'mcp.json'),'--settings',str(settings),
            '--append-system-prompt','Risposte concise in italiano. Preserva configurazioni e artefatti. Non usare subagenti salvo autorizzazione esplicita. Usa Headroom per output lunghi, mantenendo recuperabili gli originali e senza dichiarare risparmi non misurati.']
        if session and any((harness.home/'projects').glob('*/'+session+'.jsonl')):args.extend(['--resume',session])
        self.transport.start({'mode':'claude','binary':harness.binary,'args':args,'cwd':str(harness.cwd),'env':harness.environment()})
        return self.status()

    def status(self):
        state=self.transport.snapshot()
        try:activity=json.loads(self.marker.read_text(encoding='utf-8'))
        except (OSError,ValueError):activity={}
        known=activity.get('token')==self.token and activity.get('known') is True
        state.update(original_ui=True,interactive=True,activity_known=known,
            busy=state['ready'] and (not known or activity.get('busy') is not False or self.has_draft),pid=self.transport.pid)
        state.pop('chunks',None)
        return state

    def input(self,payload):
        if payload.get('action')=='resize':
            if any(type(payload.get(key)) is not int or not 10<=payload[key]<=400 for key in ('cols','rows')):raise ValueError('Dimensioni terminale non valide')
            self.transport.send({key:payload[key] for key in ('action','cols','rows')})
        elif payload.get('action')=='input':
            data=payload.get('data')
            if not isinstance(data,str) or len(data)>8192:raise ValueError('Input terminale non valido')
            if '\r' in data or '\n' in data:self.has_draft=False
            elif any(character.isprintable() for character in re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',data)):self.has_draft=True
            self.transport.send({'action':'input','data':data})
        else:raise ValueError('Azione terminale non valida')
        return {'ok':True}

    def close(self,automatic=False):
        state=self.status()
        if state['busy']:raise RuntimeError('Claude Code occupato o con testo da conservare: usa /exit nell’interfaccia originale')
        if automatic and state['ready'] and time.monotonic()-self.transport.last_output<30:raise RuntimeError('Il terminale originale sta ancora producendo output')
        self.transport.close()
