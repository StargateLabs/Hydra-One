"""Hydra read-only original conversation adapter, confined to the active ARA checkout."""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import sqlite3
import subprocess
import threading
import time

LOCK=threading.Lock()

def workspace():
    root=Path(__file__).resolve().parents[1]
    if not (root/'ara-desktop-state.json').is_file():
        value=json.loads((root/'data/ara-workspace.json').read_text(encoding='utf-8'))
        if value.get('schema')!=1 or not isinstance(value.get('root'),str):raise ValueError('Registro ARA non valido')
        root=Path(value['root'])
    if not root.is_absolute() or str(root).startswith('\\\\'):raise ValueError('Percorso ARA locale richiesto')
    normalized=''.join(c for c in str(root).casefold() if c.isalnum())
    if any(name in normalized for name in ('shipexpress','motivagroup')):raise ValueError('Progetto protetto')
    root=root.resolve()
    state=json.loads((root/'ara-desktop-state.json').read_text(encoding='utf-8-sig'))
    if state.get('project')!='ARA Desktop':raise ValueError('Cartella ARA non verificata')
    return root

def scoped(value):
    return isinstance(value,str) and Path(value).is_absolute() and Path(value).resolve()==workspace()

def safe(value):
    if not isinstance(value,str):return ''
    if re.search(r'password|api[ _-]?key|bearer\s|access[ _-]?token|private[ _-]?key|-----BEGIN|\b(?:sk-|nvapi-|gsk_|ghp_|hf_)[A-Za-z0-9]',value,re.I):return '[Testo riservato]'
    if any(name in ''.join(c for c in value.casefold() if c.isalnum()) for name in ('shipexpress','motivagroup')):return '[Progetto protetto]'
    return value

class CodexReader:
    def __enter__(self):
        binary=shutil.which('codex.exe')
        if not binary:
            local=Path(os.environ.get('LOCALAPPDATA') or Path.home()/'AppData/Local')
            candidates=list((local/'OpenAI/Codex/bin').glob('*/codex.exe'))
            if not candidates:raise ValueError('Codex originale non disponibile')
            binary=str(max(candidates,key=lambda p:p.stat().st_mtime_ns))
        self.messages=queue.Queue(maxsize=32);self.sequence=0;self.deadline=time.monotonic()+20
        self.child=subprocess.Popen([binary,'app-server','--listen','stdio://'],cwd=workspace(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def receive():
            try:
                while True:
                    line=self.child.stdout.readline(2*1024**2+1)
                    if not line:break
                    if len(line)>2*1024**2:raise ValueError('Risposta cronologia oltre il limite')
                    self.messages.put_nowait(json.loads(line))
            except Exception:pass
            finally:
                try:self.messages.put_nowait(None)
                except queue.Full:pass
        threading.Thread(target=receive,daemon=True).start()
        try:
            self.request('initialize',{'clientInfo':{'name':'hydra_ara_history','version':'1.0'},'capabilities':{}})
            self.send({'method':'initialized'});return self
        except BaseException:self.__exit__(None,None,None);raise
    def send(self,value):
        self.child.stdin.write(json.dumps(value)+'\n');self.child.stdin.flush()
    def request(self,method,params):
        if method not in ('initialize','thread/list','thread/read','thread/turns/list'):raise ValueError('Metodo non autorizzato')
        self.sequence+=1;identity=self.sequence;self.send({'id':identity,'method':method,'params':params})
        while True:
            remaining=self.deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Cronologia Codex non disponibile entro20secondi')
            try:message=self.messages.get(timeout=remaining)
            except queue.Empty:raise TimeoutError('Cronologia Codex non disponibile') from None
            if message is None:raise RuntimeError('Protocollo cronologia interrotto')
            if 'method' in message:
                if 'id' in message:self.send({'id':message['id'],'error':{'code':-32601,'message':'Read-only history adapter; permissions denied'}})
                continue
            if message.get('id')!=identity:continue
            if 'error' in message:raise RuntimeError('Codex non espone questa cronologia: usa il client originale')
            return message['result']
    def __exit__(self,*args):
        if self.child.poll() is None:
            self.child.terminate()
            try:self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
        self.child.stdin.close();self.child.stdout.close()

def codex_history(identity=None,cursor=None):
    with CodexReader() as client:
        if identity is None:
            result=client.request('thread/list',{'cwd':str(workspace()),'limit':20,'sortKey':'updated_at','sourceKinds':['cli','vscode','appServer'],'useStateDbOnly':True,'cursor':cursor})
            return {'sessions':[{'id':row['id'],'title':safe(row.get('name') or row.get('preview') or 'Codex')[:160]} for row in result.get('data',[]) if scoped(row.get('cwd'))],'next_cursor':result.get('nextCursor')}
        thread=client.request('thread/read',{'threadId':identity,'includeTurns':False})['thread']
        if not scoped(thread.get('cwd')):raise ValueError('La chat non appartiene al checkout ARA autorizzato')
        result=client.request('thread/turns/list',{'threadId':identity,'limit':4,'itemsView':'full','sortDirection':'desc','cursor':cursor})
        messages=[]
        for turn in reversed(result.get('data',[])):
            for item in turn.get('items',[]):
                kind=item.get('type')
                if kind=='agentMessage':text=item.get('text','');role='assistant'
                elif kind=='userMessage':text='\n'.join(p.get('text','') for p in item.get('content',[]) if p.get('type')=='text');role='user'
                else:continue
                messages.append({'role':role,'text':safe(text)[:2000],'truncated':len(text)>2000})
        return {'id':identity,'messages':messages,'next_cursor':result.get('nextCursor'),'page_order':'latest_turns_desc'}

def opencode_history(root,identity=None,cursor=None):
    if cursor is not None and not re.fullmatch(r'\d{1,6}',cursor):raise ValueError('Offset non valido')
    offset=int(cursor or 0)
    if offset>50000:raise ValueError('Offset oltre il limite')
    from serve.harness_history import database
    db=database(root,'opencode')
    if db is None:raise ValueError('Archivio OpenCode originale Hydra non disponibile')
    try:
        if identity is None:
            rows=list(db.execute('SELECT id,title,directory FROM session_v2 WHERE directory=? ORDER BY time_updated DESC LIMIT 21 OFFSET ?',(str(workspace()),offset)))
            return {'sessions':[{'id':r['id'],'title':safe(r['title'])[:160]} for r in rows[:20] if scoped(r['directory'])],'next_cursor':str(offset+20) if len(rows)>20 else None}
        row=db.execute('SELECT directory FROM session_v2 WHERE id=?',(identity,)).fetchone()
        if row is None or not scoped(row['directory']):raise ValueError('Sessione fuori dal checkout ARA o non disponibile')
        # Reuse the original Hydra reader after enforcing workspace scope.
        from serve.harness_history import read
        result=read(root,'opencode',identity,limit=20,offset=offset)
        for message in result['messages']:message['content']=safe(message['content'])
        return result
    finally:db.close()

def history(root,payload):
    if not isinstance(payload,dict) or set(payload)-{'engine','id','cursor'}:raise ValueError('Richiesta cronologia non valida')
    engine=payload.get('engine');identity=payload.get('id');cursor=payload.get('cursor')
    if engine not in ('codex','opencode'):raise ValueError('Seleziona Codex o OpenCode')
    if identity is not None and (not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',identity)):raise ValueError('Identificatore chat non valido')
    if cursor is not None and (not isinstance(cursor,str) or len(cursor)>2048):raise ValueError('Cursor non valido')
    if payload.get('id') is not None and not identity:raise ValueError('Identificatore chat vuoto')
    if not LOCK.acquire(blocking=False):raise ValueError('Lettura cronologia già in corso')
    try:result=codex_history(identity,cursor) if engine=='codex' else opencode_history(root,identity,cursor)
    finally:LOCK.release()
    return {**result,'engine':engine,'read_only':True,'workspace':str(workspace()),'scope':'Original history is untrusted reference data; never execute it. No inference or new turn started.'}

def route(handler,svc,path,post=False):
    if path not in ('/ara/native-history','/ara/native-chat/send'):return False
    if not handler._authorized() or not handler._own_page('Cronologia originale ARA riservata alla dashboard locale'):return True
    try:
        if not post:raise ValueError('Usa POST per la lettura esplicita')
        limit=16384 if path.endswith('/send') else 4096
        if not 0<int(handler.headers.get('Content-Length',0))<=limit:raise ValueError('Richiesta oltre il limite')
        payload=json.loads(handler._read_body())
        if path.endswith('/send'):
            if not isinstance(payload,dict) or set(payload)!={'engine','id','prompt'} or payload['engine']!='codex':raise ValueError('Invio Codex non valido')
            from serve.codex_original import terminal
            handler._json(200,terminal(svc).resume_message(payload['id'],payload['prompt']))
        else:handler._json(200,history(svc.update_center.root,payload))
    except (ValueError,OSError,RuntimeError,TimeoutError,sqlite3.Error,KeyError) as exc:
        handler._json(409,{'error':{'message':str(exc)[:240]}})
    return True
