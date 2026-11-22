"""Our download adapter against original storage/routes in an isolated fixture.

No voice synthesis, model loading, user database writes or live job modification.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import sys
import uuid

root = Path(__file__).resolve().parents[1]
fixture = root / 'tmp' / ('voice-longform-proof-' + uuid.uuid4().hex[:10])
fixture.mkdir(parents=True)
os.environ.update(OMNIVOICE_DATA_DIR=str(fixture), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.dont_write_bytecode = True
native = Path(os.environ['APPDATA']) / 'VoiceStudio/runtime/project/backend'
sys.path[:0] = [str(root), str(native), str(native.parent)]
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from api.routers import longform_jobs, audiobook
from services import longform_resume
from core import job_store
from core.db import init_db, DB_PATH
from serve.voicestudio_jobs import action

assert Path(DB_PATH).resolve().is_relative_to(fixture.resolve()), DB_PATH
init_db()
outputs = fixture / 'outputs'
outputs.mkdir(exist_ok=True)
audio = outputs / 'fixture.mp3'
subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.2',
                '-c:a', 'libmp3lame', str(audio)], check=True, timeout=20,
               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
job_store.create('fixture-book', type='audiobook', meta={'title': 'Isolated download fixture'})
job_store.append_event('fixture-book', json.dumps({'type': 'done', 'output': audio.name, 'chapters': 1, 'duration_s': .2}))
job_store.mark_done('fixture-book')
app = FastAPI()
app.include_router(longform_jobs.router)
app.include_router(audiobook.router)
app.mount('/audio', StaticFiles(directory=outputs), name='audio')
http = TestClient(app)

class OriginalFixtureClient:
    def __init__(self):
        self._busy = threading.Lock()
    def _ready(self):
        pass
    def _request(self, route, payload=None, timeout=15, limit=1024*1024, raw_body=None, content_type=None):
        response = http.post(route, content=raw_body, headers={'Content-Type': content_type}) if raw_body is not None else http.get(route)
        response.raise_for_status()
        assert len(response.content) <= limit
        return response.content, 'fixture-route', response.headers.get('content-type', '')

before = job_store.list_jobs(limit=100)
result = action(OriginalFixtureClient(), {'kind': 'longform', 'action': 'download', 'id': 'fixture-book'})
assert base64.b64decode(result['file_base64']) == audio.read_bytes()
assert job_store.list_jobs(limit=100) == before
manifest = longform_resume.build_manifest(job_id='interrupted-fixture', job_type='audiobook',
                                         plan_chapters=[{'title': 'Saved chapter', 'spans': []}],
                                         params={'fmt': 'mp3', 'default_voice': 'saved-voice'})
manifest_path = Path(longform_resume.write_manifest(manifest))
job_store.create('interrupted-fixture', type='audiobook')
job_store.mark_failed('interrupted-fixture', 'Isolated interruption fixture')
manifest_before = manifest_path.read_bytes()
listed = http.get('/audiobook/jobs').json()['jobs']
assert any(row['job_id'] == 'interrupted-fixture' and row['status'] == 'failed' for row in listed)
assert http.post('/audiobook/resume/missing-fixture', json={}).status_code == 404
assert manifest_path.read_bytes() == manifest_before
from serve.voicestudio_render import render_payload
options = {'text': '# Saved chapter\nText', 'line_gap_ms': 350, 'paragraph_gap_ms': 500,
           'trim_edges': False, 'num_step': 32, 'guidance_scale': 2.0,
           'position_temperature': 0.0, 'class_temperature': 0.0,
           'postprocess_output': False, 'seed': 0, 'emo_text': 'calm', 'emo_alpha': .5,
           'vary_repeats': True}
original_request = audiobook.AudiobookRequest.model_validate(render_payload(options))
for key, value in options.items():
    assert getattr(original_request, key) == value
plain = audiobook.AudiobookRequest.model_validate(render_payload({'text': 'Chapter'}))
assert not (set(options) - {'text'}) & plain.model_fields_set
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aS1EAAAAASUVORK5CYII=')
cover = action(OriginalFixtureClient(), {'kind': 'audiobook', 'action': 'cover', 'file_name': 'fixture.png',
                                       'file_base64': base64.b64encode(png).decode()})
cover_file = Path(audiobook._safe_cover_path(cover['cover_path']))
assert cover_file.resolve().is_relative_to(fixture.resolve()) and cover_file.read_bytes() == png
assert render_payload({'text': 'Chapter', 'cover_path': cover['cover_path']})['cover_path'] == cover_file.name
proof = {'scope': 'original_storage_and_routes_with_isolated_sine_fixture',
         'download_bytes_preserved': True, 'original_job_records_preserved': True,
         'filename': result['filename'], 'mime': result['mime'],
         'sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
         'native_router_sha256': hashlib.sha256(Path(longform_jobs.__file__).read_bytes()).hexdigest(),
         'original_resumable_manifest_listed': True, 'missing_resume_rejected': True,
         'saved_manifest_preserved': True, 'resume_synthesis_executed': False,
         'native_optional_options_schema_verified': True, 'unset_native_options_preserved': True,
         'native_cover_upload_bytes_preserved': True, 'native_cover_token_confined': True,
         'user_records_modified': False, 'model_loaded': False, 'voice_synthesized': False}
(root / 'output/verification/voice-longform-native-download-20261014.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
print('PASS: original library route, MP3 download, exact bytes and persisted job preservation; isolated fixture only.')
