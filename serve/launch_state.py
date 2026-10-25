"""Only operational launches may become the dashboard's remembered profile."""
import json
from pathlib import Path
import time
from serve.configuration import atomic_json

def operational_profile(config, root):
    path = Path(config).resolve()
    try:
        relative = path.relative_to(Path(root).resolve())
    except ValueError:
        return False
    return path.is_file() and not any(part.lower() in ('output', 'verification', 'benchmarks') for part in relative.parts)

def remember_launch(data, root, config, port):
    if port not in (8088,8090) or not operational_profile(config, root):
        return False
    atomic_json(Path(data)/'ultimo-avvio.json',dict(config=str(Path(config).resolve()),port=port,when=time.time()))
    return True

def selected_profile(root, state):
    fallback = Path(root)/'strata-iq3_xxs.json'
    try:
        saved = json.loads(Path(state).read_text(encoding='utf-8-sig'))
        if saved.get('port') in (8088,8090) and operational_profile(saved['config'],root):
            return Path(saved['config']).resolve()
    except (OSError,ValueError,KeyError,TypeError):
        pass
    return fallback.resolve()

if __name__ == '__main__':
    import sys
    print(selected_profile(sys.argv[1],sys.argv[2]))
