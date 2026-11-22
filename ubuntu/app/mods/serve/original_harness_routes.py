"""Same-page authenticated routes to the original interactive applications."""
import json,threading
from urllib.parse import parse_qs,urlsplit
_creation_lock=threading.Lock()


def claude(svc):
    from serve.original_harness_transport import ClaudeTerminal
    from serve.server import agent_harness_for
    harness=agent_harness_for(svc,'claude','127.0.0.1:'+str(getattr(svc,'port',8090)))
    with harness.lock:
        if not hasattr(harness,'terminal'):harness.terminal=ClaudeTerminal(harness)
    return harness.terminal


def antigravity(svc):
    from serve.antigravity_original import AntigravityOriginal
    with _creation_lock:
        if not hasattr(svc,'antigravity_original'):svc.antigravity_original=AntigravityOriginal(svc.update_center.root)
    return svc.antigravity_original


def get(handler,svc,path):
    if path not in ('/harness/claude/terminal','/harness/antigravity/original','/harness/antigravity/frame'):return False
    if not handler._own_page('interfaccia originale riservata alla dashboard'):return True
    try:
        after=int(parse_qs(urlsplit(handler.path).query).get('after',['0'])[0])
        if after<0:raise ValueError('Cursore non valido')
        (claude(svc) if path=='/harness/claude/terminal' else antigravity(svc)).transport.touch()
        state={**claude(svc).transport.snapshot(after),**{key:value for key,value in claude(svc).status().items() if key in ('busy','activity_known')}} if path=='/harness/claude/terminal' else antigravity(svc).frame(after) if path.endswith('/frame') else antigravity(svc).status()
        handler._json(200,state)
    except Exception as error:handler._json(400,{'error':{'message':str(error)}})
    return True


def post(handler,svc,path):
    parts=path.split('/')
    if len(parts)!=5 or parts[1]!='harness' or (parts[2],parts[3]) not in (('claude','terminal'),('antigravity','original')) or parts[4] not in ('start','input','stop'):return False
    if not handler._own_page('interfaccia originale gestita da questa pagina'):return True
    try:
        if not 0<int(handler.headers.get('Content-Length',0))<=32768:raise ValueError('Richiesta non valida')
        payload=json.loads(handler._read_body())
        if not isinstance(payload,dict):raise ValueError('Richiesta oggetto JSON')
        app=claude(svc) if parts[2]=='claude' else antigravity(svc)
        result=app.start() if parts[4]=='start' else app.input(payload) if parts[4]=='input' else app.close(automatic=payload.get('automatic_idle') is True) if parts[2]=='claude' else app.close()
        handler._json(200,result or {'ok':True})
    except Exception as error:handler._json(409,{'error':{'message':str(error)}})
    return True
