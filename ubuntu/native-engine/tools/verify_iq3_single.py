"""One short real request, no retries or automatic model restart."""
import json
import sys
import urllib.request

url, output = sys.argv[1:]
body = {'model':'qwen3.8-flash-next-iq3_xxs', 'messages':[{'role':'user','content':'Quanto fa 19 + 23? Rispondi soltanto con il numero.'}],
        'max_tokens':32,'temperature':0,'top_k':1,'reasoning_effort':'none'}
request = urllib.request.Request(url+'/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=120) as response:
    result = json.load(response)
text = result['choices'][0]['message']['content'].strip()
from pathlib import Path
Path(output).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
if text != '42':
    raise RuntimeError('Short quality probe failed: '+repr(text))
print('Single IQ3_XXS request: answer 42, PASS')
