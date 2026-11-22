"""Hydra frame for the original ARA-owned Superagent; no model or second UI."""
import json
import urllib.error
import urllib.request

ARA = 'http://127.0.0.1:8777'


def local(action='status'):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if action == 'status':
        with opener.open(ARA + '/api/superagent', timeout=8) as response:
            return json.load(response)
    with opener.open(ARA + '/api/control', timeout=8) as response:
        token = json.load(response)['token']
    request = urllib.request.Request(ARA + '/api/superagent', method='POST',
        data=json.dumps({'action': action, 'payload': {}}).encode(),
        headers={'Content-Type': 'application/json', 'Origin': ARA, 'X-ARA-Token': token})
    with opener.open(request, timeout=50) as response:
        return json.load(response)


def route(handler, svc, path, *, post=False):
    if path not in ('/harness/superara/status', '/harness/superara/start', '/harness/superara/connect', '/harness/superara/stop'):
        return False
    if not handler._own_page('Super Ara Agent uses the original authenticated interface'):
        return True
    operation = path.rsplit('/', 1)[1]
    if post == (operation == 'status'):
        handler._json(405, {'error': {'message': 'Method not allowed'}})
        return True
    try:
        if post:
            body = json.loads(handler._read_body() or b'{}')
            if body != {}: raise ValueError('No arguments accepted')
        if operation == 'connect':
            value = local('connect')
        else:
            current = local('start' if operation == 'start' else 'shutdown' if operation == 'stop' else 'status')
            native = current.get('native', {})
            running = current.get('running') is True
            ready = native.get('health', {}).get('runtime', {}).get('state') == 'ready'
            load = native.get('load', {})
            value = {'status': 'ready' if running and ready else 'starting' if running else 'idle',
                'installed': current.get('installed', True), 'pid': current.get('pid'),
                'busy': bool(load.get('running') or load.get('queued')), 'activity_known': True,
                'tools': 'ARA', 'original_ui': True, 'binding': {'model': 'ARA selected cloud', 'context': 'native'},
                'url': 'http://127.0.0.1:3082/' if running else None}
        handler._json(200, value)
    except (OSError, ValueError, urllib.error.URLError) as error:
        handler._json(409, {'error': {'message': 'Super Ara Agent: ' + type(error).__name__ + '. Verifica lo stato ARA.'}})
    return True
