"""Offline validation/plan commands; stdio serving requires explicit live-I/O opt-in."""
import argparse
from dataclasses import asdict
import json
import sys

from .backend import HTTPBackend, inspect_backend, launch_plan
from .config import Config, static_profile
from .core import Engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['validate', 'inspect', 'plan', 'stdio', 'stdio-duplex'])
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = Config.load(args.config)
    if args.command == 'validate':
        print(json.dumps(dict(valid=True, config=asdict(config), collection_authorized=False)))
    elif args.command == 'inspect':
        print(json.dumps(inspect_backend(config)))
    elif args.command == 'plan':
        from urllib.parse import urlsplit
        print(json.dumps(dict(executed=False, profile=static_profile(config),
                             argv=launch_plan(config, port=urlsplit(config.backend_url).port))))
    else:
        if args.command == 'stdio-duplex':
            from .duplex import serve
        else:
            from .sidecar import serve
        backend = HTTPBackend(config)
        if config.enabled and config.live_io_authorized:
            identity = backend.prepare()
            if identity['state'] != 'prepared':
                print(json.dumps(dict(type='unavailable', data=identity)), file=sys.stderr)
                return 2
        result = serve(sys.stdin, sys.stdout, Engine(config, lambda: backend))
        if args.command == 'stdio-duplex' and (result['state'] != 'closed' or result['output_failed']):
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
