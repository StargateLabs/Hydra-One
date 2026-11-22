"""Read-only source inventory. Presence is never a claim of functional parity."""
import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    ('strata', 'Strata', 'serve/server.py', 'serve/web/unified-engine-control.js', 'serve/test_dashboard_cold_start.py'),
    ('llama', 'llama.cpp', 'serve/optional_backends.py', 'serve/web/optional-backends.js', 'serve/test_optional_workflow.py'),
    ('transformers', 'Transformers / Safetensors', 'serve/optional_inference.py', 'serve/web/optional-backends.js', 'serve/test_optional_workflow.py'),
    ('unsloth', 'Unsloth', 'serve/local_training.py', 'serve/web/training-native-app.js', 'serve/test_training_methods.py'),
    ('soup', 'Soup', 'serve/soup_runtime.py', 'serve/web/local-training.js', 'serve/test_soup_runtime.py'),
    ('airllm', 'AirLLM', 'serve/airllm_runtime.py', 'serve/web/airllm-ui.js', 'serve/test_airllm_runtime.py'),
    ('voicestudio', 'VoiceStudio', 'serve/voicestudio.py', 'serve/web/voicestudio.js', 'serve/test_voicestudio.py'),
    ('openwebui', 'Open WebUI', 'serve/open_webui_runtime.py', 'serve/web/open-webui-documents.js', 'serve/test_open_webui_runtime.py'),
    ('whisper', 'whisper.cpp', 'serve/local_audio.py', 'serve/web/local-audio.js', 'serve/test_local_audio.py'),
    ('audio', 'audio.cpp / Kokoro / PocketTTS', 'serve/local_speech.py', 'serve/web/local-speech.js', 'serve/test_local_audio.py'),
    ('demucs', 'HTDemucs', 'serve/local_separation.py', 'serve/web/local-separation.js', 'serve/test_local_separation.py'),
    ('musicgen', 'MusicGen / AudioCraft', 'serve/local_generative_audio.py', 'serve/web/local-generation.js', 'serve/test_local_generative_audio.py'),
    ('openvoice', 'OpenVoice', 'serve/local_generative_audio.py', 'serve/web/local-generation.js', 'serve/test_local_generative_audio.py'),
    ('diffusers', 'Diffusers / Stable Diffusion / SDXL', 'serve/local_visual_generation.py', 'serve/web/local-generation.js', 'serve/test_local_visual_generation.py'),
    ('modelscope', 'ModelScope video', 'serve/local_visual_generation.py', 'serve/web/local-generation.js', 'serve/test_local_visual_generation.py'),
    ('claude', 'Claude Code', 'serve/claude_harness.py', 'serve/web/original-harness-ui.js', 'serve/test_claude_harness.py'),
    ('antigravity', 'Antigravity Desktop', 'serve/antigravity_original.py', 'serve/web/original-harness-ui.js', 'serve/test_original_harness_transport.py'),
    *[(identifier, name, 'serve/agent_harness.py', 'serve/web/agent-harness.js', 'serve/test_agent_harness.py') for identifier, name in
      [('opencode', 'OpenCode'), ('hermes', 'Hermes Agent'), ('trueforge', 'TrueForge'), ('dsh', 'DeepSeek Harness')]],
]

def voice_routes(directory):
    routes = []
    errors = []
    for file in sorted(directory.glob('*.py')):
        try:
            tree = ast.parse(file.read_text(encoding='utf-8-sig'))
        except (OSError, SyntaxError) as error:
            errors.append({'file': file.name, 'error': str(error)})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ('get', 'post', 'put', 'patch', 'delete', 'websocket'):
                    if decorator.args and isinstance(decorator.args[0], ast.Constant):
                        routes.append({'module': file.stem, 'method': decorator.func.attr.upper(), 'local_path': decorator.args[0].value, 'function': node.name, 'line': node.lineno})
    return routes, errors

def main():
    rows = []
    for identifier, name, backend, ui, test in ROWS:
        files = {'backend': backend, 'interface': ui, 'tests': test}
        tree = ast.parse((ROOT / backend).read_text(encoding='utf-8-sig'))
        actions = sorted(set(re.findall(r"(?:fetch|request)\(\s*['\"]([^'\"]+)", (ROOT / ui).read_text(encoding='utf-8'))))
        rows.append({'id': identifier, 'name': name, 'files': files,
                     'source_presence': {key: (ROOT / value).is_file() for key, value in files.items()},
                     'backend_function_inventory': sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}),
                     'static_ui_request_literals': actions,
                     'upstream_parity_verified': False,
                     'status': 'source_checked; functional_scope_requires_individual_review'})
    config = json.loads((ROOT / 'data/mcp-dashboard.json').read_text(encoding='utf-8'))
    original = Path.home() / 'AppData/Local/Programs/VoiceStudio/resources/backend/api/routers'
    routes, errors = voice_routes(original)
    proof = {'checked_at': datetime.now(timezone.utc).isoformat(), 'scope': 'local source inventory only; no apps started or original data changed',
             'apps': rows, 'mcp_servers': list(config['mcpServers']),
             'voicestudio_original_router_inventory': {'directory_present': original.is_dir(), 'routes': routes, 'parse_errors': errors},
             'limits': ['Decorator paths exclude router prefixes and are not runtime availability proof.',
                        'Backend functions include helpers; request literals omit dynamic URLs and shared controllers. Neither count measures coverage.',
                        'Internal endpoints and account/license features require classification, not automatic exposure.',
                        'Passing project tests does not establish all upstream functions are exposed.']}
    output = ROOT / 'output/verification/interface-coverage-audit.json'
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'apps': len(rows), 'mcp_servers': len(config['mcpServers']), 'missing_source_files': [(row['name'], key, row['files'][key]) for row in rows for key, exists in row['source_presence'].items() if not exists], 'voice_original_routes': len(routes), 'voice_parse_errors': len(errors)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
