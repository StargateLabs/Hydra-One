"""Small deterministic task evaluation; separate from throughput and broad model quality."""
import argparse
import datetime
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from serve.configuration import atomic_json

CASES = [
    ('invoice', 'Prezzi 19, 37 e 44 euro. Sconto del 15% sul totale, poi spedizione 7 euro. Quanto paghi? Restituisci {"total":numero}.', {'total':92}),
    ('sort', 'Ordina per punteggio decrescente, poi nome crescente: Ada=8, Leo=9, Bea=8, Mia=9. Restituisci {"names":[nomi]}.', {'names':['Leo','Mia','Ada','Bea']}),
    ('aggregate', 'Vendite: nord 12, sud 7, nord 5, est 9, sud 4. Somma per zona. Restituisci un oggetto con nord,sud,est.', {'nord':17,'sud':11,'est':9}),
    ('trace_python', 'Esegui mentalmente Python: a=[2,3,5,7]; b=[x*x for x in a if x%2]; print(sum(b)). Restituisci {"result":numero}.', {'result':83}),
    ('trace_loop', 'Python: n=1\nfor i in range(1,5):\n n=n*2+i\nQuale n finale? Restituisci {"n":numero}.', {'n':42}),
    ('interval', 'Quali interi soddisfano 2*x+3>11 e 3*x-1<=20? Restituisci {"values":[interi in ordine crescente]}.', {'values':[5,6,7]}),
    ('deduplicate', 'Elimina duplicati mantenendo prima occorrenza: [4,2,4,1,2,7,1]. Restituisci {"values":[numeri]}.', {'values':[4,2,1,7]}),
    ('join', 'Clienti: id1 Ada, id2 Bea, id3 Leo. Ordini: cliente2 10 euro; cliente1 12; cliente2 7. Restituisci totali per nome, includi chi non ha ordini.', {'Ada':12,'Bea':17,'Leo':0}),
    ('schedule', 'A dura 3 minuti. B dura 5 e parte dopo A. C dura 4 e parte dopo A, parallela a B. D dura 2 e parte dopo B e C. Durata minima totale? {"minutes":numero}.', {'minutes':10}),
    ('nested', 'Dati {"items":[{"active":true,"v":4},{"active":false,"v":20},{"active":true,"v":7}]}. Somma v solo degli active. Restituisci {"sum":numero}.', {'sum':11}),
    ('logic', 'Tutti i robot blu hanno un sensore. R1 e blu. R2 ha un sensore ma il colore non e noto. Quale robot sicuramente blu? Restituisci {"certain_blue":[id]}.', {'certain_blue':['R1']}),
    ('date', 'Il 28 febbraio 2024, aggiungendo due giorni, quale data ISO si ottiene? Restituisci {"date":"YYYY-MM-DD"}.', {'date':'2024-03-01'}),
]

def evaluate(answer, expected):
    def matches(actual, reference):
        if isinstance(reference, dict):
            return isinstance(actual, dict) and actual.keys() == reference.keys() and all(matches(actual[k],v) for k,v in reference.items())
        if isinstance(reference, list):
            return isinstance(actual, list) and len(actual) == len(reference) and all(matches(a,b) for a,b in zip(actual,reference))
        if isinstance(reference, (int,float)) and not isinstance(reference,bool):
            return isinstance(actual,(int,float)) and not isinstance(actual,bool) and actual == reference
        return type(actual) is type(reference) and actual == reference
    try:
        return matches(json.loads(answer),expected)
    except (ValueError, TypeError):
        return False

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stop-file',type=Path)
    a=p.parse_args()
    url=a.url.rstrip('/')
    def request(path,body=None):
        headers={'Content-Type':'application/json'}
        if os.environ.get('STRATA_API_KEY'):headers['Authorization']='Bearer '+os.environ['STRATA_API_KEY']
        req=urllib.request.Request(url+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
        with urllib.request.urlopen(req,timeout=180) as r:return json.load(r)
    health=request('/health')
    if not health.get('model'):raise RuntimeError('Model identity unavailable')
    from serve.quality_suite import DATASET_SHA256
    report={'kind':'12 deterministic tasks; not a general quality benchmark','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'running','model':health['model'],'cases':[],'dataset_sha256':DATASET_SHA256}
    atomic_json(a.output,report)
    try:
        for name,prompt,expected in CASES:
            if getattr(a,'stop_file',None) and a.stop_file.exists():raise InterruptedError('Arresto richiesto fra i compiti')
            start=time.perf_counter()
            result=request('/v1/chat/completions',{'model':health['model'],'messages':[{'role':'user','content':prompt+' Rispondi soltanto con JSON, senza spiegazioni.'}],'temperature':0,'top_k':1,'top_p':1,'min_p':0,'seed':42,'reasoning_effort':'none','max_tokens':160})
            answer=result['choices'][0]['message']['content']
            usage=result['usage']
            if not answer or usage.get('completion_tokens',0)<=0:raise RuntimeError('Empty task response')
            report['cases'].append({'case':name,'answer':answer,'expected':expected,'passed':evaluate(answer,expected),'finish_reason':result['choices'][0].get('finish_reason'),'usage':usage,'wall_s':time.perf_counter()-start})
            atomic_json(a.output,report)
        report.update(status='complete',correct=sum(c['passed'] for c in report['cases']),total=len(CASES))
        report['passed']=report['correct']==report['total']
        atomic_json(a.output,report)
        print(f"Tasks: {report['correct']}/{report['total']}",flush=True)
        return 0 if report['passed'] else 2
    except Exception as exc:
        report.update(status='error',error=str(exc),passed=False)
        atomic_json(a.output,report)
        raise

if __name__=='__main__':sys.exit(main())
