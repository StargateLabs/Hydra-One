"""Read-only original inventories and invalid resume guards; no render starts."""
import json
from pathlib import Path
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[1]
base = 'http://127.0.0.1:8090'
def call(path, payload=None):
    request = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                    headers={'Content-Type': 'application/json', 'Origin': base,
                                             'X-Strata-Voice-Request': 'strata-resume-guard-proof'})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)

status, before = call('/voicestudio/activities')
assert status == 200 and before.get('groups'), before
checks = []
for payload in ({'resume_job_id': '../invalid'}, {'resume_job_id': 'strata-missing-resume-fixture'},
                {'text': 'Guard fixture only', 'num_step': 0},
                {'text': 'Guard fixture only', 'postprocess_output': 'false'}):
    status, value = call('/voicestudio/audiobook/render', payload)
    assert status == 400, (status, value)
    checks.append({'status': status, 'message': value['error']['message']})
status, after = call('/voicestudio/activities')
assert status == 200 and before == after
status, metrics = call('/metrics')
assert status == 200
proof = {'checks': checks, 'groups': [group['kind'] for group in after['groups']],
         'counts': {group['kind']: len(group['jobs']) for group in after['groups']},
         'records_identical': before == after, 'engine': metrics['live']['state'], 'render_started': False}
(root / 'output/verification/voice-resume-live-guards-20261014.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
print(json.dumps(proof))
