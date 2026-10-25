"""Atomic campaign reservation. Never steal another process' reservation."""
import json
import os
from pathlib import Path
import time
import uuid

class GpuLease:
    def __init__(self,root,owner):
        self.path=Path(root)/'data/.gpu-campaign.lock';self.owner=owner;self.token=uuid.uuid4().hex;self.held=False
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        try:fd=os.open(self.path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise RuntimeError('Una campagna riserva già la GPU; attendi la conclusione') from None
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(dict(owner=self.owner,token=self.token,pid=os.getpid(),created_at=time.time()),stream)
        self.held=True
        return self
    def release(self):
        if not self.held:return
        try:
            if json.loads(self.path.read_text())['token']==self.token:self.path.unlink()
        except (OSError,ValueError,KeyError):pass
        self.held=False
    def __enter__(self):return self.acquire()
    def __exit__(self,*args):self.release()

def reserved(root):return (Path(root)/'data/.gpu-campaign.lock').exists()

def recover_stale_optional_reservation(root):
    return _recover_stale_reservation(root,'optional-backend',(8091,8092))

def recover_stale_colibri_reservation(root):
    import psutil
    try:
        home=Path(root)/'data/colibri'
        setup=json.loads((home/'setup.json').read_text(encoding='utf-8'))
        marker=json.loads((home/'strata-runtime.json').read_text(encoding='utf-8'))
        port=setup.get('port');pid=marker.get('pid')
        if setup.get('host')!='127.0.0.1' or type(port) is not int or not 1<=port<=65535:return False
        if type(pid) is not int or psutil.pid_exists(pid):return False
        return _recover_stale_reservation(root,'colibri-original-workspace',(port,))
    except (OSError,ValueError,psutil.Error):return False

def _recover_stale_reservation(root,owner,ports):
    """Archive only a dead optional owner with no child and no listening backend."""
    import psutil
    import re
    import socket
    path=Path(root)/'data/.gpu-campaign.lock'
    try:
        original=path.read_bytes();entry=json.loads(original)
        pid=entry.get('pid');token=entry.get('token')
        if entry.get('owner')!=owner or type(pid) is not int or not isinstance(token,str) or not re.fullmatch(r'[a-f0-9]{32}',token):return False
        if psutil.pid_exists(pid):return False
        if any(process.info.get('ppid')==pid for process in psutil.process_iter(['pid','ppid'])):return False
        for port in ports:
            with socket.socket() as probe:
                probe.settimeout(.3)
                if probe.connect_ex(('127.0.0.1',port))==0:return False
        if path.read_bytes()!=original:return False
        archive=Path(root)/'data/stale-reservations';archive.mkdir(parents=True,exist_ok=True)
        destination=archive/(token+'.json')
        if destination.exists():return False
        path.rename(destination)
        return True
    except (OSError,ValueError,psutil.Error):return False


def owns_inherited_validation_lease(root):
    """Only the verifier's actual descendant may use its existing reservation."""
    import psutil
    token=os.environ.get('STRATA_VALIDATION_LEASE_TOKEN')
    if not token:return False
    try:
        entry=json.loads((Path(root)/'data/.gpu-campaign.lock').read_text(encoding='utf-8'))
        return entry.get('owner')=='strata-bounded-check' and entry.get('token')==token and entry.get('pid') in {parent.pid for parent in psutil.Process().parents()}
    except (OSError,ValueError,psutil.Error):return False
