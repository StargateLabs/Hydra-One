"""Small live IQ3 smoke suite; records answers and assertions, not a model benchmark."""
import json
import argparse
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.configuration import atomic_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',default='http://127.0.0.1:8088')
parser.add_argument('--output',type=Path,default=Path('output/verification/iq3-live-quality.json'))
parser.add_argument('--expected-model',help='Explicit identity for an alternative model; default remains IQ3_XXS')
options = parser.parse_args()
URL = options.url.rstrip('/')
OUT = options.output
started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
atomic_json(OUT,{"status":"running","passed":False,"started_at":started_at})
def request(path, body=None):
    r = urllib.request.Request(URL+path, data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(r, timeout=1200) as f: return json.load(f)

health = request("/health")
if options.expected_model:assert health['model']==options.expected_model,health
else:assert 'iq3_xxs' in health['model'].lower(),health
cases = [
    ("arithmetic", "Quanto fa 17 * 23? Rispondi solo con il numero.", lambda s: s.strip() == "391"),
    ("context", "Il codice riservato per questa prova è ZAFFIRO-821. Ripeti solo il codice, senza spiegazioni.", lambda s: s.strip() == "ZAFFIRO-821"),
    ("italian", "Scrivi una frase breve in italiano che spieghi cosa significa eseguire un modello in locale.", lambda s: len(s.split()) >= 5 and any(w in s.lower() for w in ("computer","dispositivo","pc","macchina"))),
]
rows=[]
for name,prompt,check in cases:
    t=time.perf_counter()
    result=request("/v1/chat/completions", {"model":health["model"],"messages":[{"role":"user","content":prompt}],
        "temperature":0,"top_k":1,"max_tokens":100,"reasoning_effort":"none"})
    answer=result["choices"][0]["message"]["content"]
    rows.append({"case":name,"answer":answer,"passed":bool(check(answer)),"wall_s":time.perf_counter()-t,"usage":result["usage"]})

result=request("/v1/chat/completions", {"model":health["model"],"messages":[{"role":"user","content":'Restituisci un oggetto JSON con chiave "ok" uguale a true e "sum" uguale a 12.'}],
    "response_format":{"type":"json_object"},"temperature":0,"top_k":1,"max_tokens":100,"reasoning_effort":"none"})
answer=result["choices"][0]["message"]["content"]
try: obj=json.loads(answer); passed=obj.get("ok") is True and obj.get("sum")==12
except (ValueError,AttributeError): passed=False
rows.append({"case":"structured_json","answer":answer,"passed":passed})
schema={"type":"object","properties":{"ok":{"type":"boolean","const":True},"sum":{"type":"integer","const":12}},
        "required":["ok","sum"],"additionalProperties":False}
result=request("/v1/chat/completions", {"model":health["model"],"messages":[{"role":"user","content":'Restituisci ok=true e sum=12.'}],
    "response_format":{"type":"json_schema","json_schema":{"name":"check_sum","strict":True,"schema":schema}},
    "temperature":0,"top_k":1,"max_tokens":100,"reasoning_effort":"none"})
answer=result["choices"][0]["message"]["content"]
from jsonschema import validate, ValidationError
try: validate(json.loads(answer),schema); passed=True
except (ValueError,ValidationError): passed=False
rows.append({"case":"structured_schema","answer":answer,"passed":passed})
result=request("/v1/messages", {"model":health["model"],"messages":[{"role":"user","content":"Quanto fa 12 + 30? Rispondi solo con il numero."}],
    "max_tokens":50,"temperature":0,"thinking":{"type":"disabled"}})
answer="".join(x.get("text","") for x in result.get("content",[]) if x.get("type")=="text")
rows.append({"case":"anthropic_api","answer":answer,"passed":answer.strip()=="42"})

body={"model":health["model"],"messages":[{"role":"user","content":"Ripeti solo la parola pronto."}],
      "max_tokens":30,"temperature":0,"reasoning_effort":"none","stream":True}
r=urllib.request.Request(URL+"/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
parts=[]; done=False
with urllib.request.urlopen(r,timeout=1200) as f:
    for raw in f:
        line=raw.decode().strip()
        if line=="data: [DONE]": done=True
        elif line.startswith("data: "):
            chunk=json.loads(line[6:])
            for choice in chunk.get("choices",[]): parts.append(choice.get("delta",{}).get("content") or "")
answer="".join(parts)
rows.append({"case":"openai_stream","answer":answer,"done":done,"passed":done and answer.strip().lower().strip('.!')=="pronto"})
body["messages"][0]["content"]="Scrivi un saggio molto lungo sulla storia dell'informatica."
body["max_tokens"]=1000
r=urllib.request.Request(URL+"/v1/chat/completions",data=json.dumps(body).encode(),headers={"Content-Type":"application/json"})
received=False
with urllib.request.urlopen(r,timeout=1200) as f:
    for raw in f:
        line=raw.decode().strip()
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk=json.loads(line[6:])
            if any(c.get("delta",{}).get("content") for c in chunk.get("choices",[])):
                received=True; break
deadline=time.monotonic()+10
while True:
    state=request("/metrics")["live"]["state"]
    if state in ("idle","unloaded") or time.monotonic()>=deadline: break
    time.sleep(.25)
rows.append({"case":"client_cancel","received_token":received,"final_state":state,"passed":received and state in ("idle","unloaded")})
report={"status":"complete","started_at":started_at,"model":health["model"],"kind":"live functional smoke, not a general quality evaluation","cases":rows,
        "passed":all(r["passed"] for r in rows)}
atomic_json(OUT,report)
print(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if report["passed"] else 1)
