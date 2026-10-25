"""LocalAI Windows container for the existing dashboard and original native apps."""
import argparse,ctypes,hashlib,json,os,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.configuration import atomic_json
from serve.native_workspace import browser_executable,validated_base_url
from serve.native_window_host import NativeWindowHost

class Workspace:
    def __init__(self,root,base_url):
        import tkinter as tk
        import psutil
        self.tk=tk;self.root=Path(root).resolve();self.base_url=validated_base_url(base_url)
        self.folder=self.root/'data/native-workspace';self.folder.mkdir(parents=True,exist_ok=True)
        self.state_file=self.folder/'state.json';self.command_file=self.folder/'command.json'
        self.process_created_at=psutil.Process().create_time();self.dock=NativeWindowHost()
        self.pending={};self.children={};self.selected='dashboard';self.command_id=None;self.error=None
        self.last_state=None;self.closing=False;self.close_started=None;self.last_activity=time.monotonic()
        self.window=tk.Tk();self.window.title('StargateLab LocalAI');self.window.geometry('1440x940');self.window.minsize(960,640)
        self.app_icon=tk.PhotoImage(file=str(self.root/'serve/web/stargatelab-localai-logo.png'));self.window.iconphoto(True,self.app_icon)
        self.window.configure(bg='#11191e')
        bar=tk.Frame(self.window,bg='#172129',height=64);bar.pack(side='top',fill='x');bar.pack_propagate(False)
        self.header_icon=self.app_icon.subsample(max(1,self.app_icon.width()//32))
        tk.Label(bar,text='  STARGATELAB  /  LocalAI',image=self.header_icon,compound='left',fg='#e9f2f8',bg='#172129',font=('Segoe UI',12,'bold')).pack(side='left',padx=20)
        self.buttons={};self.brand_icons={}
        for kind,title in [('dashboard','Dashboard'),('claude','Claude · originale'),('antigravity','Antigravity · originale')]:
            button=tk.Button(bar,text=title,command=lambda name=kind:self.select(name),bg='#23333e',fg='#e9f2f8',activebackground='#2bcc9b',activeforeground='#102019',relief='flat',borderwidth=0,padx=17,pady=10,font=('Segoe UI',10))
            brand={'claude':'brand-claude-desktop.png','antigravity':'brand-antigravity.png'}.get(kind)
            if brand and (self.root/'serve/web'/brand).is_file():
                image=tk.PhotoImage(file=str(self.root/'serve/web'/brand));image=image.subsample(max(1,image.width()//24))
                self.brand_icons[kind]=image;button.configure(image=image,compound='left')
            button.pack(side='left',padx=4,pady=9);self.buttons[kind]=button
        self.message=tk.StringVar(value='Avvio della dashboard…')
        tk.Label(self.window,textvariable=self.message,bg='#11191e',fg='#a9bdc9',anchor='w',font=('Segoe UI',10)).pack(side='bottom',fill='x',padx=16,pady=7)
        self.container=tk.Frame(self.window,bg='#11191e');self.container.pack(fill='both',expand=True)
        self.pages={}
        for kind in ('dashboard','claude','antigravity'):
            page=tk.Frame(self.container,bg='#11191e');page.place(x=0,y=0,relwidth=1,relheight=1);self.pages[kind]=page
            tk.Label(page,text='Caricamento dell’interfaccia originale…',bg='#11191e',fg='#a9bdc9',font=('Segoe UI',14)).pack(expand=True)
        self.window.update_idletasks();self.window.update()
        self.container.bind('<Configure>',lambda event:self.resize())
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.window.bind_all('<KeyPress>',lambda event:self.touch(),add='+')
        self.window.bind_all('<Button>',lambda event:self.touch(),add='+')
        self.select('dashboard');self.window.after(150,self.tick)

    def touch(self):
        self.last_activity=time.monotonic()

    def executable(self,kind):
        if kind=='dashboard':return browser_executable()
        if kind=='claude':
            from serve.claude_desktop import executable
        else:
            from serve.antigravity_desktop import executable
        return executable()

    def select(self,kind):
        if kind not in self.pages or self.closing:return
        if self.selected!=kind and self.selected in self.dock.windows:self.dock.windows[self.selected]['last_used']=time.monotonic()
        self.touch();self.selected=kind;self.pages[kind].lift()
        for name,button in self.buttons.items():button.configure(bg='#2bcc9b' if name==kind else '#23333e',fg='#102019' if name==kind else '#e9f2f8')
        row=self.dock.windows.get(kind)
        if row and self.dock.gui.IsWindow(row['hwnd']):
            if row['closing']:
                self.message.set('Chiusura sicura in corso · attendi prima di riaprire '+kind);return
            self.error=None;self.dock.show(kind);self.message.set('Interfaccia originale dentro LocalAI · '+kind);return
        if kind in self.pending:return
        self.error=None
        path=self.executable(kind)
        if path is None:self.error='Programma originale non installato: '+kind;self.message.set(self.error);return
        current=self.dock.top_windows();baseline={row['hwnd'] for row in current}
        if kind!='dashboard':
            # An existing app remains owned by the user and is restored on host exit.
            existing=self.find_matching(current,kind,path)
            if existing:
                try:self.dock.dock(kind,existing['hwnd'],self.pages[kind].winfo_id(),False);self.dock.show(kind);self.message.set('Interfaccia originale integrata · sessione esistente conservata')
                except Exception as error:self.error=str(error);self.message.set(self.error)
                return
        command=[str(path)]
        if kind=='dashboard':
            command.extend(['--app='+self.base_url+'/?native_workspace=1','--user-data-dir='+str(self.folder/'dashboard-profile'),
                            '--no-first-run','--no-default-browser-check','--disable-background-mode','--disable-component-update','--disable-sync','--disable-crash-reporter'])
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        process=subprocess.Popen(command,cwd=self.root if kind=='dashboard' else path.parent,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 startupinfo=startup,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0),close_fds=True)
        self.children[kind]=process;self.pending[kind]={'path':path,'baseline':baseline,'started':time.monotonic(),'pid':process.pid}
        self.message.set('Avvio originale dentro LocalAI · '+kind)

    def find_matching(self,windows,kind,path):
        import psutil
        for row in windows:
            try:
                process=psutil.Process(row['pid']);binary=Path(process.exe())
                if kind=='dashboard':
                    if binary.name.lower() not in ('chrome.exe','msedge.exe'):continue
                    if '--user-data-dir='+str(self.folder/'dashboard-profile') not in process.cmdline():continue
                elif kind=='antigravity':
                    if binary.name.lower()!='antigravity.exe' or not binary.resolve().is_relative_to(path.parent.resolve()):continue
                elif binary.name.lower()!='claude.exe' or not binary.resolve().is_relative_to(path.parent.resolve()):continue
                return row
            except (OSError,ValueError,psutil.Error):continue
        return None

    def resize(self):
        for kind in tuple(self.dock.windows):self.dock.resize(kind)

    def close_app(self,kind,automatic=False):
        row=self.dock.windows.get(kind)
        if not row:return
        if automatic and not row['owned']:return
        self.dock.close(kind)
        if self.selected==kind and kind!='dashboard':self.select('dashboard')

    def command(self):
        try:
            if self.command_file.stat().st_size>8192:return
            command=json.loads(self.command_file.read_text(encoding='utf-8'))
            if command.get('id')==self.command_id or time.time()-command.get('created_at',0)>90:return
            self.command_id=command.get('id');kind=command.get('kind');action=command.get('action')
            if kind not in self.pages:return
            if action=='open':
                self.window.deiconify();self.window.lift();self.select(kind)
            elif action=='close':self.close_app(kind,automatic=True)
            elif action=='close_workspace':self.close()
        except (OSError,ValueError,TypeError):pass

    def tick(self):
        try:
            self.command()
            for kind,job in list(self.pending.items()):
                windows=[row for row in self.dock.top_windows() if row['hwnd'] not in job['baseline']]
                match=self.find_matching(windows,kind,job['path'])
                if match:
                    self.dock.dock(kind,match['hwnd'],self.pages[kind].winfo_id(),True);self.pending.pop(kind)
                    if self.closing:self.dock.close(kind)
                    self.dock.show(self.selected);self.message.set('Interfaccia originale integrata · '+self.selected)
                elif time.monotonic()-job['started']>45:
                    self.pending.pop(kind);self.error='L’interfaccia originale non ha creato una finestra integrabile: '+kind;self.message.set(self.error)
            windows=self.dock.snapshot()
            for kind,row in list(self.dock.windows.items()):
                if kind!=self.selected and kind!='dashboard' and not row['closing'] and time.monotonic()-row['last_used']>=30:
                    self.close_app(kind,automatic=True)
                if row['closing'] and row.get('shutdown_result',{}).get('stopped') is False and self.dock.gui.IsWindow(row['hwnd']):
                    row['closing']=False
                    self.error='Chiusura in attesa dell’app: controlla eventuali richieste di salvataggio · '+kind
                    self.message.set(self.error)
            state={'pid':os.getpid(),'process_created_at':self.process_created_at,'ready':'dashboard' in windows,'selected':self.selected,
                   'windows':windows,'pending':list(self.pending),'error':self.error,'closing':self.closing,'updated_at':time.time()}
            key=json.dumps({k:v for k,v in state.items() if k!='updated_at'},sort_keys=True)
            if key!=self.last_state:atomic_json(self.state_file,state);self.last_state=key
            if self.closing:
                # Never force-kill a native app with an unsaved-document dialog.
                if not windows and not self.pending:self.window.destroy();return
                if time.monotonic()-self.close_started>40:
                    self.closing=False;self.error='Completa la chiusura o il salvataggio richiesto dall’app.';self.message.set(self.error)
        except Exception as error:
            self.error=str(error);self.message.set(self.error)
            print(type(error).__name__,str(error),flush=True)
        self.window.after(200,self.tick)

    def close(self):
        if self.closing:return
        self.closing=True;self.close_started=time.monotonic()
        for kind,row in list(self.dock.windows.items()):
            if row['owned']:self.dock.close(kind)
            else:self.dock.restore(kind)
        for kind in list(self.pending):
            # Pending processes are not forcibly killed; discover their window first.
            self.error='Attendi l’avvio prima di chiudere il contenitore.'

    def run(self):
        self.window.mainloop()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);parser.add_argument('--base-url',required=True)
    args=parser.parse_args();base=validated_base_url(args.base_url)
    if os.name!='nt':raise RuntimeError('Windows native workspace only')
    import win32event,win32api,winerror
    name='Local\\StargateLabNativeWorkspace-'+hashlib.sha256((str(args.root.resolve())+base).encode()).hexdigest()[:20]
    mutex=win32event.CreateMutex(None,False,name)
    if win32api.GetLastError()==winerror.ERROR_ALREADY_EXISTS:return
    try:
        try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError,OSError):pass
        Workspace(args.root,base).run()
    finally:win32api.CloseHandle(mutex)

if __name__=='__main__':main()
