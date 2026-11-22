"""Real image-path smoke test; restores images to off after the test."""
import base64
import json
from pathlib import Path
import struct
import sys
import urllib.request
import urllib.error
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from serve.configuration import atomic_json

def request(path, body=None):
    r=urllib.request.Request('http://127.0.0.1:8088'+path,data=json.dumps(body).encode() if body is not None else None,
                             headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(r,timeout=1200) as f:return json.load(f)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e
def chunk(kind,data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
image=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',128,128,8,2,0,0,0))
image+=chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\x00\x00'*128)*128))+chunk(b'IEND',b'')
health=request('/health')
if health.get('images'):raise RuntimeError('Requires images initially off, so the original state can be restored')
report={'model':health['model'],'kind':'single synthetic image smoke, not a general vision evaluation','passed':False}
try:
    request('/config',{'vision':True})
    result=request('/v1/chat/completions',{'model':health['model'],'messages':[{'role':'user','content':[
        {'type':'text','text':'Qual è il colore dominante di questa immagine? Rispondi con una sola parola in italiano.'},
        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image).decode()}}]}],
        'temperature':0,'top_k':1,'max_tokens':50,'reasoning_effort':'none'})
    answer=result['choices'][0]['message']['content']
    report.update(answer=answer,passed='rosso' in answer.lower(),usage=result['usage'])
except Exception as e:
    report['error']=str(e)
finally:
    request('/config',{'vision':False})
    report['restored_images_off']=not request('/health').get('images')
    atomic_json(Path('output/verification/iq3-live-vision.json'),report)
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report['passed'] and report['restored_images_off'] else 1)
