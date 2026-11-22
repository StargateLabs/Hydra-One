"""Create a fresh official Claude Desktop local gateway profile.

Format verified against installed original Desktop 2.19675.1 app.asar:
configLibrary/_meta.json selects a UUID.json flat configuration document.
Existing user configurations are never replaced.
"""
import json
import os
from pathlib import Path

PROFILE_ID = 'a301dc19-30be-4f65-ad1c-2700e851a865'


def configure(base=None):
    base = Path(base or os.environ['LOCALAPPDATA'])
    library = base / 'Claude-3p' / 'configLibrary'
    if library.exists():
        raise RuntimeError('Existing Claude Desktop configuration preserved; no changes made.')
    library.mkdir(parents=True)
    profile = {
        'inferenceProvider': 'gateway',
        'inferenceGatewayBaseUrl': 'http://127.0.0.1:8090',
        'inferenceGatewayApiKey': 'none',
        'inferenceGatewayAuthScheme': 'bearer',
        'inferenceCredentialKind': 'static',
        'deploymentOrganizationUuid': PROFILE_ID,
    }
    metadata = {'appliedId': PROFILE_ID, 'entries': [{'id': PROFILE_ID, 'name': 'Strata locale'}]}
    (library / (PROFILE_ID + '.json')).write_text(json.dumps(profile, indent=2), encoding='utf8')
    (library / '_meta.json').write_text(json.dumps(metadata, indent=2), encoding='utf8')
    return library


if __name__ == '__main__':
    print(configure())
