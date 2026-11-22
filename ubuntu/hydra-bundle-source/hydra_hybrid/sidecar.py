"""Sequential stdio JSONL service; no listening socket or automatic native startup."""
from dataclasses import asdict
import json


def serve(source, destination, engine):
    def send(value):
        destination.write(json.dumps(value, allow_nan=False) + '\n')
        destination.flush()
    try:
        while True:
            line = source.readline(engine.config.budget.request_bytes + 1)
            if not line:
                break
            ident = None
            iterator = None
            try:
                if len(line.encode('utf-8')) > engine.config.budget.request_bytes or not line.endswith('\n'):
                    raise ValueError('Oversized or incomplete JSONL frame; close channel')
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('JSON object required')
                ident = message.get('id')
                if not isinstance(ident, str) or len(ident) > 128:
                    raise ValueError('Bounded string request id required')
                if message.get('type') == 'health':
                    send(dict(id=ident, type='health', data=engine.status()))
                    continue
                iterator = engine.stream(message['request'])
                for event in iterator:
                    send(dict(id=ident, type='event', event=asdict(event)))
            except Exception as exc:
                send(dict(id=ident, type='error', error_type=type(exc).__name__, message=str(exc)))
                if not line.endswith('\n'):
                    break
            finally:
                if iterator is not None:
                    iterator.close()
    finally:
        if not engine.close():
            send(dict(id=None, type='shutdown_uncertain', data=engine.status()))
