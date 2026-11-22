"""Register the isolated Graphify runtime without replacing other MCP entries."""
import json
import shutil
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parent.parent
python = root / 'tools/graphify/venv/Scripts/python.exe'
graph = root / 'graphify-out/graph.json'
config = Path.home() / '.codex/config.toml'
raw = config.read_text(encoding='utf-8')
parsed = tomllib.loads(raw)
entry = {'command': str(python), 'args': ['-m', 'graphify.serve', '--graph', str(graph)],
         'env': {'GRAPHIFY_QUERY_LOG_DISABLE': '1'}}
existing = parsed.get('mcp_servers', {}).get('graphify')
if existing and existing != entry:
    raise SystemExit('Existing Graphify registration differs; preserved for review.')
if not existing:
    backup = config.with_name('config.toml.before-graphify.backup')
    if not backup.exists():
        shutil.copyfile(config, backup)
    addition = '\n[mcp_servers.graphify]\ncommand = ' + json.dumps(str(python))
    addition += '\nargs = ' + json.dumps(entry['args'])
    addition += '\n[mcp_servers.graphify.env]\nGRAPHIFY_QUERY_LOG_DISABLE = "1"\n'
    updated = raw + addition
    assert tomllib.loads(updated)['mcp_servers']['graphify'] == entry
    config.write_text(updated, encoding='utf-8')
# Upstream installs can choose the system executable even when run in a venv.
hooks = root / '.codex/hooks.json'
data = json.loads(hooks.read_text(encoding='utf-8'))
for group in data.get('hooks', {}).get('PreToolUse', []):
    for hook in group.get('hooks', []):
        if 'graphify' in hook.get('command', '') and 'hook-check' in hook['command']:
            hook['command'] = '"' + str(python) + '" -m graphify hook-check'
hooks.write_text(json.dumps(data, indent=2), encoding='utf-8')
print('Graphify MCP registered; original configuration backed up; hook uses isolated runtime.')
