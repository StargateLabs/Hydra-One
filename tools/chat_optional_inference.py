"""Explicit opt-in CLI for already configured Unsloth/llama.cpp local APIs.

Does not install/start an inference engine or change the dashboard model.
"""
import argparse
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serve.optional_inference import LocalOpenAIBackend
from serve.gpu_lease import GpuLease


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Endpoint locale /v1 del backend separato')
    parser.add_argument('--model', help='ID effettivo restituito da /v1/models')
    parser.add_argument('--models', action='store_true', help='Solo verifica API: nessuna generazione')
    parser.add_argument('--prompt')
    parser.add_argument('--max-tokens', type=int, default=128)
    parser.add_argument('--api-key-env', help='Nome della variabile di ambiente, mai la chiave in argv')
    args = parser.parse_args()
    import os
    key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not key:
        parser.error('Variabile di autenticazione mancante')
    backend = LocalOpenAIBackend(args.url, key)
    if args.models:
        print(json.dumps(backend.models(), ensure_ascii=False, indent=2))
        return
    if not args.model or not args.prompt:
        parser.error('La generazione richiede --model e --prompt espliciti')
    request = urllib.request.Request('http://127.0.0.1:8088/metrics')
    operational_key = os.environ.get('STRATA_API_KEY')
    if operational_key:
        request.add_header('Authorization', 'Bearer ' + operational_key)
    with urllib.request.urlopen(request, timeout=5) as response:
        live = json.load(response)['live']
    if live['state'] != 'unloaded' or live.get('queued'):
        raise RuntimeError('Ferma il motore operativo prima di usare un altro backend sulla GPU')
    with GpuLease(ROOT, 'optional-inference-chat'):
        for event in backend.chat([dict(role='user', content=args.prompt)], args.model,
                                  args.max_tokens, stream=True):
            for choice in event['choices']:
                text = choice.get('delta', {}).get('content')
                if text:
                    print(text, end='', flush=True)
        print()


if __name__ == '__main__':
    main()
