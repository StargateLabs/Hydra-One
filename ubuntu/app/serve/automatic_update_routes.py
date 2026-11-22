"""Authenticated controls for automatic, non-destructive updates."""
import json
def get(handler,service,path):
    if path!='/updates/automatic':return False
    if handler._authorized():handler._json(200,service.automatic_updates.status())
    return True
def post(handler,service,path):
    if path not in ('/updates/automatic/check','/updates/automatic/configure','/updates/restart'):return False
    if not handler._own_page('aggiornamenti automatici gestiti da LocalAI'):return True
    try:
        if not 0<int(handler.headers.get('Content-Length',0))<=1024:raise ValueError('Invalid automatic update request size')
        body=json.loads(handler._read_body())
        if not isinstance(body,dict):raise ValueError('Send a JSON object')
        if path=='/updates/restart':
            if not service.update_center.operational_idle() or not service.automatic_updates.activities_idle():raise ValueError('Il riavvio attende la fine delle attività in corso')
            service.automatic_restart();handler._json(202,{'restarting':True});return True
        if 'enabled' in body and not isinstance(body['enabled'],bool):raise ValueError('enabled must be a boolean')
        result=service.automatic_updates.check() if path.endswith('/check') else service.automatic_updates.configure(body.get('enabled',True))
        handler._json(200,result)
    except (OSError,ValueError,RuntimeError) as error:handler._json(400,{'error':{'message':str(error)}})
    return True
