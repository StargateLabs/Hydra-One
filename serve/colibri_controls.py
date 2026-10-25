"""Colibri operations used by the existing Strata controls."""
import json
import urllib.error
import urllib.request
import http.client
import socket
import threading
from urllib.parse import urlsplit

READ_PATHS = ('health', 'profile', 'experts', 'v1/models', 'metrics')


def request(workspace, path, body=None, *, state=None, cancel=None):
    if path not in READ_PATHS and not (path == 'v1/systemone' and body is not None):
        raise ValueError('Operazione Colibri non supportata')
    state = workspace.status() if state is None else state
    if state['status'] != 'ready':
        raise ValueError('Colibri non è pronto')
    base = state['urls']['anthropic_base_url'].rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password:
        raise ValueError('Endpoint Colibri non valido')
    encoded = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(base + '/' + path, data=encoded,
                                 headers={'Content-Type': 'application/json'})
    if body is not None:
        connection=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=5)
        finished=threading.Event()
        def watch():
            while not finished.wait(.05):
                if cancel is not None and cancel.is_set():
                    try:connection.sock.shutdown(socket.SHUT_RDWR)
                    except (OSError,AttributeError):pass
                    connection.close();return
        if cancel is not None:threading.Thread(target=watch,daemon=True).start()
        try:
            connection.connect()
            if cancel is not None and cancel.is_set():raise ValueError('Operazione annullata')
            connection.sock.settimeout(None)
            connection.request('POST','/'+path,body=encoded,headers={'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(2*1024**2+1)
            if len(raw)>2*1024**2:raise ValueError('Risposta Colibri troppo grande')
            result=json.loads(raw)
            if response.status!=200:raise ValueError((result.get('error') or {}).get('message','Richiesta Colibri rifiutata'))
            return result
        finally:finished.set();connection.close()
    try:
        with urllib.request.urlopen(req, timeout=90 if body is not None else 4) as response:
            raw = response.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise ValueError('Risposta Colibri troppo grande')
        return raw.decode('utf-8',errors='replace') if path=='metrics' else json.loads(raw)
    except urllib.error.HTTPError as error:
        detail = error.read(8192).decode('utf-8', errors='replace')
        raise ValueError('Colibri: ' + detail) from error


def telemetry(workspace):
    state=workspace.status()
    result = {'workspace':state,'context':workspace.context_configuration()}
    try:
        config=json.loads((workspace.home/'setup.json').read_text(encoding='utf-8'))
        result['configuration']={key:config.get(key) for key in ('model','family','backend','gpu','engine_source','model_dir','host','port','version','updated','engine','launcher')}
    except (OSError,ValueError):result['configuration']={}
    result['logs']={}
    for label,path in [('motore',workspace.home/'logs/serve.log'),('preparazione',workspace.home/'setup.log')]:
        try:
            with path.open('rb') as log:
                log.seek(0,2);size=log.tell();log.seek(max(0,size-16384));result['logs'][label]=log.read(16384).decode('utf-8',errors='replace')
        except OSError:result['logs'][label]='Nessun log disponibile'
    if state['status']!='ready':
        result.update(health={},profile={'turns':[]},experts={},v1_models={})
        return result
    for path in READ_PATHS:
        try:result[path.replace('/', '_')] = request(workspace, path, state=state)
        except (OSError,ValueError):result[path.replace('/', '_')] = {'unavailable':True}
    return result


def require_idle(health):
    scheduler = health.get('scheduler')
    if (not isinstance(scheduler, dict) or type(scheduler.get('active')) is not int
            or type(scheduler.get('queued')) is not int):
        raise ValueError('Attività Colibri non verificabile')
    if scheduler['active'] or scheduler['queued']:
        raise ValueError('Colibri ha richieste attive o in coda')


def stop(workspace):
    if not workspace.lease or not workspace.lease.held:
        raise ValueError('Il processo Colibri non appartiene a questa sessione')
    require_idle(request(workspace, 'health'))
    import subprocess
    completed = subprocess.run(workspace._command('stop'), cwd=workspace.source,
                               env=workspace._environment(), capture_output=True,
                               text=True, encoding='utf-8', timeout=40,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout)[-1200:])
    state=workspace.status()
    if state['status'] not in ('stopped','unconfigured'):
        raise ValueError('Il motore è ancora attivo; nessun secondo avvio eseguito')
    return state


def decide(workspace, payload, cancel=None):
    def bounded(value,limit,label):
        if not isinstance(value,(str,dict,list)) or len(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))>limit:
            raise ValueError(label+' non valido o troppo lungo')
    if not isinstance(payload,dict) or 'state' not in payload:raise ValueError('Documento non valido')
    bounded(payload['state'],200000,'Contesto')
    questions=payload.get('questions')
    if not isinstance(questions,dict) or not 1<=len(questions)<=64:raise ValueError('Inserisci da 1 a 64 domande')
    for key,question in questions.items():
        if not isinstance(key,str) or not 1<=len(key)<=128 or not isinstance(question,dict):raise ValueError('Identita domanda non valida')
        bounded(question.get('instructions',''),2000,'Domanda')
        kind=question.get('type');criteria=question.get('criteria')
        if kind=='choice':
            if not isinstance(criteria,dict) or not 1<=len(criteria)<=255 or any(not isinstance(k,str) or not k.strip() or len(k)>2000 for k in criteria):raise ValueError('Scelta: da 1 a 255 opzioni con etichette distinte')
        elif kind=='score':
            if not isinstance(criteria,list) or not 1<=len(criteria)<=255:raise ValueError('Punteggio: da 1 a 255 livelli')
        elif kind=='noul':
            if criteria is not None and (not isinstance(criteria,dict) or any(k not in ('true','false') for k in criteria)):raise ValueError('Si/No: criteri true e false facoltativi')
        else:raise ValueError('Tipo domanda non supportato')
        for value in criteria.values() if isinstance(criteria,dict) else criteria or []:
            if value is not None:bounded(value,2000,'Descrizione criterio')
    if 'normalize' in payload and payload['normalize'] not in ('sum','mean'):raise ValueError('Normalizzazione: sum oppure mean')
    if 'pin_state' in payload and type(payload['pin_state']) is not bool:raise ValueError('Cache contesto: valore booleano richiesto')
    if 'prefix' in payload:bounded(payload['prefix'],20000,'Istruzioni persistenti')
    if 'prefix' in payload and not isinstance(payload['prefix'],str):raise ValueError('Istruzioni persistenti: testo richiesto')
    if 'cache_slot' in payload and (type(payload['cache_slot']) is not int or not 0<=payload['cache_slot']<=1023):raise ValueError('Sessione KV non valida')
    allowed=('state','questions','normalize','pin_state','prefix','cache_slot')
    body={key:payload[key] for key in allowed if key in payload};body['model']=workspace.status()['model_id']
    return request(workspace,'v1/systemone',body,cancel=cancel)
