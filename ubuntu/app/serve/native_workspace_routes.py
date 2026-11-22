"""Loopback, authenticated commands for the original native UI container."""
import json,threading
from pathlib import Path
from serve.native_workspace import NativeWorkspace,KINDS
_creation_lock=threading.Lock()

def manager(handler,service):
    with _creation_lock:
        if getattr(service,'native_workspace',None) is None:
            root=service.optional_backends.root
            service.native_workspace=NativeWorkspace(root,'http://127.0.0.1:'+str(handler.server.server_port))
        return service.native_workspace

def get(handler,service,path):
    if path!='/native-workspace':return False
    if not handler._authorized():return True
    handler._json(200,manager(handler,service).status());return True

def post(handler,service,path):
    if path not in ('/native-workspace/open','/native-workspace/stop','/native-workspace/close'):return False
    if not handler._own_page('interfacce native dentro LocalAI'):return True
    try:
        if not 0<int(handler.headers.get('Content-Length',0))<=2048:raise ValueError('Invalid native workspace request size')
        payload=json.loads(handler._read_body())
        if not isinstance(payload,dict):raise ValueError('Send a JSON object')
        kind=payload.get('kind','dashboard')
        if kind not in KINDS:raise ValueError('Unknown native application')
        if path.endswith('/open'):
            handler._json(410,{'error':{'message':'Contenitore desktop disattivato. Apri le interfacce originali nella sezione Harness della dashboard.'}})
            return True
        workspace=manager(handler,service)
        result=workspace.open(kind) if path.endswith('/open') else workspace.stop_app(kind) if path.endswith('/stop') else workspace.close()
        handler._json(200,result)
    except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
    return True
