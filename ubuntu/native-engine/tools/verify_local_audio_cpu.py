import base64,json,urllib.request
from pathlib import Path
root=Path.cwd();base='http://127.0.0.1:8088';body={'name':'jfk.wav','language':'en','audio_base64':base64.b64encode((root/'output/verification/audio-jfk.wav').read_bytes()).decode()}
request=urllib.request.Request(base+'/local-audio/transcribe',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
with urllib.request.urlopen(request,timeout=120) as response:report=json.load(response)
assert 'country' in report['text'].lower();assert report['device']=='cpu'
(root/'output/verification/local-audio-cpu-real.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
