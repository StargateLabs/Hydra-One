"""Exercise installed original profile APIs on an isolated fixture database.

No user voices, projects, tokens, model weights or original source files are changed.
This verifies API/storage contracts, not voice-cloning quality or ASR inference.
Run with the app-private VoiceStudio Python environment.
"""
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import wave
import uuid

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tmp'/('voice-native-contract-proof-'+uuid.uuid4().hex[:10])
if not FIXTURE.resolve().is_relative_to((ROOT/'tmp').resolve()):raise RuntimeError('Fixture escaped workspace')
FIXTURE.mkdir(parents=True,exist_ok=True)
sys.dont_write_bytecode=True
os.environ.update(OMNIVOICE_DATA_DIR=str(FIXTURE),HF_HOME=str(FIXTURE/'hf'),HF_HUB_CACHE=str(FIXTURE/'hf/hub'),HF_TOKEN_PATH=str(FIXTURE/'hf/token'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
resources=Path(os.environ['LOCALAPPDATA'])/'Programs/VoiceStudio/resources'
sys.path[:0]=[str(ROOT),str(resources/'backend'),str(resources)]
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routers import profiles,personas,pronunciation,describe_voice
from core.db import init_db,DB_PATH
if not Path(DB_PATH).resolve().is_relative_to(FIXTURE.resolve()):raise RuntimeError('Original database escaped fixture')
init_db()
from serve.voicestudio import VoiceStudio

app=FastAPI()
for module in (profiles,personas,pronunciation,describe_voice):app.include_router(module.router)
@app.get('/health')
def health():return {'status':'ok','version':'original-routes-isolated-fixture','device':'cpu'}
@app.middleware('http')
async def fixture_marker(request,call_next):
    response=await call_next(request);response.headers['x-omnivoice-backend']='original-routes-isolated-fixture';return response

class Response:
    def __init__(self,response):self.status=response.status_code;self.headers=response.headers;self.body=response.content
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit=-1):return self.body if limit<0 else self.body[:limit]
class Opener:
    def __init__(self,test):self.test=test
    def open(self,request,timeout=None):
        return Response(self.test.request(request.get_method(),request.full_url.replace('http://127.0.0.1:3900',''),content=request.data,headers=dict(request.header_items())))

with TestClient(app,base_url='http://127.0.0.1:3900',client=('127.0.0.1',41000)) as test:
    connector=VoiceStudio(root=FIXTURE);connector._opener=Opener(test)
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as writer:
        writer.setnchannels(1);writer.setsampwidth(2);writer.setframerate(16000)
        writer.writeframes(b''.join(struct.pack('<h',int(2000*math.sin(2*math.pi*440*i/16000))) for i in range(16000)))
    created=connector.profile({'action':'create_clone','name':'Isolated native profile proof','language':'en','ref_text':'Fixture tone; no ASR inference claim','file_name':'reference.wav','file_base64':base64.b64encode(buffer.getvalue()).decode()})['result']
    identifier=created['id']
    assert created['kind']=='clone' and created['ref_text']=='Fixture tone; no ASR inference claim'
    updated=connector.profile({'action':'update','id':identifier,'name':'Isolated native profile renamed'})['result']
    assert updated['name']=='Isolated native profile renamed' and updated['ref_text']==created['ref_text']
    bundle=connector.profile({'action':'export','id':identifier})
    assert base64.b64decode(bundle['file_base64']).startswith(b'PK')
    inspected=connector.profile({'action':'inspect','file_base64':bundle['file_base64']})['result']
    imported=connector.profile({'action':'import','file_base64':bundle['file_base64']})['result']
    dictionary=connector.pronunciation({'action':'add','term':'StargateLab','replacement':'Star gate lab','language':'en'})['result']
    preview=connector.pronunciation({'action':'preview','text':'StargateLab','language':'en'})['result']
    assert preview['substituted']=='Star gate lab'
    connector.pronunciation({'action':'update','id':dictionary['id'],'term':'StargateLab','replacement':'Star gate lab','language':'en','enabled':False})
    assert connector.pronunciation({'action':'preview','text':'StargateLab','language':'en'})['result']['substituted']=='StargateLab'
    connector.pronunciation({'action':'import','entries':[{'term':'Fixture','replacement':'fixtur','language':'en'}]})
    assert len(test.get('/pronunciation').json())==2
    connector.pronunciation({'action':'delete','id':dictionary['id']})
    assert len(test.get('/pronunciation').json())==1
    design=connector.profile({'action':'describe','description':'female, elderly, low pitch, british accent'})['result']
    assert design['attrs']['Gender']=='female' and design['attrs']['Age']=='elderly'
    proof={'scope':'installed_original_routes_on_isolated_fixture_database','fixture_root':str(FIXTURE),'profile_create':True,'partial_update_preserves_reference':True,'native_bundle_export_inspect_import':True,'dictionary_create_update_disable_preview_import_delete':True,'native_voice_description':True,'bundle_bytes':len(base64.b64decode(bundle['file_base64'])),'original_source_sha256':{module.__name__:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (profiles,personas,pronunciation,describe_voice)},'limits':['No production user records were modified.','No ASR, voice-design synthesis or cloned-speech quality is certified by this probe.']}
    (ROOT/'output/verification/voice-original-native-contracts.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in proof.items() if isinstance(value,bool)}))
