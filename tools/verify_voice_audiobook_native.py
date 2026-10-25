"""Read-only proof of the installed audiobook parser; no synthesis or user records."""
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

root = Path(__file__).resolve().parents[1]
fixture = root / 'tmp' / ('voice-audiobook-proof-' + uuid.uuid4().hex[:10])
fixture.mkdir(parents=True, exist_ok=True)
os.environ.update(OMNIVOICE_DATA_DIR=str(fixture), HF_HOME=str(fixture / 'hf'), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.dont_write_bytecode = True
resources = Path(os.environ['LOCALAPPDATA']) / 'Programs/VoiceStudio/resources'
sys.path[:0] = [str(resources / 'backend'), str(resources)]
from services import audiobook

plan = audiobook.parse_audiobook_script('# First\nHello [pause 500ms] world\n# Second\n[voice:voice-2]Goodbye', default_voice='voice-1').to_dict()
assert plan['chapter_count'] == 2
assert plan['chapters'][0]['title'] == 'First'
assert any(span['voice_id'] == 'voice-2' for span in plan['chapters'][1]['spans'])
assert any(span['pause_ms_after'] == 500 for span in plan['chapters'][0]['spans'])
proof = {'scope': 'installed_original_parser_without_synthesis', 'chapters_voices_pauses_verified': True, 'source_sha256': hashlib.sha256(Path(audiobook.__file__).read_bytes()).hexdigest(), 'plan': plan, 'user_records_modified': False, 'model_loaded': False}
(root / 'output/verification/voice-audiobook-native-plan.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
print('Original parser: chapters, voices and pauses verified; no synthesis.')
