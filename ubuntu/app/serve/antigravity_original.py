"""Present the installed Electron renderer, retaining its original IPC and profile."""
import base64
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
import psutil
from serve.original_harness_transport import Transport


def validate_event(payload):
    if not isinstance(payload,dict):raise ValueError('Evento originale non valido')
    action=payload.get('action')
    if action=='resize':
        if any(type(payload.get(key)) is not int or not 320<=payload[key]<=3000 for key in ('width','height')):raise ValueError('Dimensioni non valide')
        return {key:payload[key] for key in ('action','width','height')}
    if action=='text':
        text=payload.get('text')
        if not isinstance(text,str) or len(text)>8192:raise ValueError('Testo non valido')
        return {'action':action,'text':text}
    params=payload.get('params')
    if action not in ('mouse','key') or not isinstance(params,dict):raise ValueError('Evento non supportato')
    if action=='mouse':
        if params.get('type') not in ('mousePressed','mouseReleased','mouseMoved','mouseWheel'):raise ValueError('Evento mouse non valido')
        for key in ('x','y'):
            if type(params.get(key)) not in (int,float) or not 0<=params[key]<=3000:raise ValueError('Coordinate non valide')
        if params.get('button','none') not in ('left','right','middle','none'):raise ValueError('Pulsante non valido')
        allowed=('type','x','y','button','buttons','clickCount','deltaX','deltaY','modifiers')
    else:
        if params.get('type') not in ('keyDown','keyUp','rawKeyDown'):raise ValueError('Evento tastiera non valido')
        allowed=('type','key','code','text','unmodifiedText','windowsVirtualKeyCode','nativeVirtualKeyCode','modifiers')
    result={key:params[key] for key in allowed if key in params}
    if len(json.dumps(result))>2048:raise ValueError('Evento troppo lungo')
    return {'action':action,'params':result}


class AntigravityOriginal:
    def __init__(self,root):
        self.root=Path(root);self.transport=Transport(root);self.child=None;self.lock=threading.RLock();self.error=None
        self.transport.idle_stop=self.close
        self.profile=Path(os.environ.get('USERPROFILE',str(Path.home())))/'AppData/Roaming/Antigravity'

    def _target(self):
        try:
            port=int((self.profile/'DevToolsActivePort').read_text().splitlines()[0])
            if not 1024<=port<=65535:return None
            # Validate that this port belongs to the installed application, not another local server.
            from serve.antigravity_desktop import executable
            binary=executable()
            owners=[row.pid for row in psutil.net_connections(kind='tcp') if row.laddr and row.laddr.port==port and row.status=='LISTEN']
            if not binary or not any(Path(psutil.Process(pid).exe()).resolve()==binary.resolve() for pid in owners):return None
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=1) as response:rows=json.load(response)
            for row in rows:
                if row.get('type')=='page' and row.get('webSocketDebuggerUrl','').startswith(f'ws://127.0.0.1:{port}/'):
                    return row
        except (OSError,ValueError,IndexError,psutil.Error):pass
        return None

    def start(self):
        from serve.antigravity_desktop import executable
        with self.lock:
            if self.transport.snapshot()['ready']:return self.status()
            # Reconnect only our renderer bridge; never restart native user sessions.
            if self.transport.child is not None:self.transport.close()
            target=self._target()
            if not target:
                path=executable()
                if not path:raise RuntimeError('Antigravity originale non installato')
                import psutil
                running=[p for p in psutil.process_iter(['exe']) if p.info['exe'] and Path(p.info['exe']).resolve()==path.resolve()]
                if running:raise RuntimeError('Antigravity è già aperto senza renderer collegabile. Chiudilo normalmente e riaprilo da Harness.')
                info=subprocess.STARTUPINFO() if os.name=='nt' else None
                if info:info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
                log=self.root/'output/verification/antigravity-native.log';log.parent.mkdir(parents=True,exist_ok=True)
                with log.open('w',encoding='utf-8') as output:
                    self.child=subprocess.Popen([str(path),'--remote-debugging-address=127.0.0.1','--remote-debugging-port=0'],
                        cwd=path.parent,stdout=output,stderr=subprocess.STDOUT,startupinfo=info)
                deadline=time.monotonic()+35
                while time.monotonic()<deadline:
                    target=self._target()
                    self._hide_owned_window()
                    if target:break
                    if self.child.poll() is not None:raise RuntimeError('Antigravity originale non si è avviato')
                    time.sleep(.3)
                if not target:raise RuntimeError('Renderer Antigravity originale non pronto')
            self.transport.start({'mode':'antigravity','url':target['webSocketDebuggerUrl']})
            self._hide_owned_window();self.error=None
            return self.status()

    def _hide_owned_window(self):
        if not self.child or self.child.poll() is not None:return
        import psutil,win32gui,win32process
        try:owned={self.child.pid,*[p.pid for p in psutil.Process(self.child.pid).children(recursive=True)]}
        except psutil.Error:return
        def visit(hwnd,_):
            if win32process.GetWindowThreadProcessId(hwnd)[1] in owned and win32gui.GetClassName(hwnd)=='Chrome_WidgetWin_1':win32gui.ShowWindow(hwnd,0)
        win32gui.EnumWindows(visit,None)

    def status(self):
        state=self.transport.snapshot();state.pop('chunks',None)
        return {**state,'original_ui':True,'preview_only':False,'native_features_available':state['ready'],
                'reconnectable':not state['ready'] and self._target() is not None,
                'inference_verified':False,'activity_known':False,'busy':state['ready'],'owned_process':bool(self.child and self.child.poll() is None)}

    def frame(self,after=0):
        with self.transport.lock:
            data=self.transport.frame
            return {'cursor':self.transport.frame_cursor,'image':data if after!=self.transport.frame_cursor else None,'viewport':self.transport.viewport,'ready':self.transport.snapshot()['ready']}

    def input(self,payload):self.transport.send(validate_event(payload));return {'ok':True}

    def close(self):
        # Detach rendering only. Native user sessions/jobs never get force-killed.
        self.transport.close()
        return {'ok':True,'detached':True,'native_session_preserved':True}
