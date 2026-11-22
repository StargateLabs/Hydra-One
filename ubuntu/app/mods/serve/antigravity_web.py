"""Own the installed Google UI's real loopback renderer in isolated preview mode.

The compiled web bundle is served by Google's shipped language_server binary.
Model, cloud and analytics endpoints are disabled for this preview. No native
Electron APIs are fabricated, and no Strata provider compatibility is claimed.
"""
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
import uuid


def command(executable,root,port,token):
    if type(port) is not int or not 1024<=port<65535 or port in (8080,8088,8090):
        raise ValueError('Choose a dedicated local preview port')
    folder=Path(root)/'data/antigravity-original-preview'
    return [str(Path(executable).parent/'resources/bin/language_server.exe'),
            '--standalone','--subclient_type=hub','--override_ide_name=antigravity',
            '--http_server_port='+str(port),'--https_server_port='+str(port+1),
            '--csrf_token='+token,'--gemini_dir='+str(folder),'--app_data_dir=antigravity','--config_dir=config',
            '--disable_telemetry','--api_server_url=http://127.0.0.1:9',
            '--cloud_code_endpoint=http://127.0.0.1:9','--inference_api_server_url=http://127.0.0.1:9',
            '--analytics_server_url=http://127.0.0.1:9','--generative_service_addr=127.0.0.1:9',
            '--exit_on_stdin_close','--use_ls_chrome_devtools_mcp=false']


class OriginalWeb:
    def __init__(self,root,busy=lambda:False,port=18196):
        self.root=Path(root);self.busy=busy;self.port=port
        self.child=None;self.lock=threading.RLock();self.error=None

    def status(self):
        with self.lock:
            ready=self.child is not None and self.child.poll() is None
            return dict(ready=ready,url='http://127.0.0.1:'+str(self.port)+'/' if ready else None,
                        original_ui=True,preview_only=True,cloud_enabled=False,
                        inference_verified=False,native_features_available=False,error=self.error)

    def start(self):
        from serve.antigravity_desktop import executable
        with self.lock:
            if self.busy():raise RuntimeError('Wait for the active response before opening the original UI')
            if self.child is not None and self.child.poll() is None:return self.status()
            path=executable()
            if path is None:raise RuntimeError('Original Antigravity is not installed')
            args=command(path,self.root,self.port,uuid.uuid4().hex)
            if not Path(args[0]).is_file():raise RuntimeError('Original Antigravity web renderer is unavailable')
            import socket
            for port in (self.port,self.port+1):
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('Original UI preview port is occupied')
            log=self.root/'output/verification/antigravity-original-web.log';log.parent.mkdir(parents=True,exist_ok=True)
            with log.open('w',encoding='utf-8') as output:
                self.child=subprocess.Popen(args,cwd=self.root,stdin=subprocess.PIPE,stdout=output,
                    stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    if self.child.poll() is not None:raise RuntimeError('Original renderer exited before readiness')
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:'+str(self.port)+'/',timeout=1) as response:
                            if 'text/html' in response.headers.get('Content-Type',''):
                                self.error=None;return self.status()
                    except OSError:pass
                    time.sleep(.2)
                raise RuntimeError('Original renderer did not serve its web UI')
            except Exception as error:
                self.error=str(error);self.close();raise

    def close(self):
        from serve.process_lifecycle import stop_owned_tree
        with self.lock:
            if self.child is not None:
                if self.child.stdin:self.child.stdin.close()
                stop_owned_tree(self.child)
                self.child=None
