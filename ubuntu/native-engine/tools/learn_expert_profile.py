"""Collect a small independent routing corpus; orderly unload saves the native profile."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import time
import urllib.request
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.configuration import atomic_json
PROMPTS = [
    'Progetta un calendario di manutenzione per un laboratorio con cinque stampanti 3D. Descrivi priorità, registrazione degli interventi e gestione dei ricambi.',
    'Spiega in italiano come organizzare un archivio fotografico personale, con nomi coerenti, copie di sicurezza e ricerca per data. Proponi una procedura pratica.',
    'Write a Python generator that reads a large CSV file incrementally and yields valid records. Explain how to handle malformed lines without loading the entire file.',
    'Descrivi i compromessi di una rete domestica con dispositivi cablati e Wi-Fi: disposizione degli access point, interferenze e misure utili per diagnosticare latenza.',
    'Explain how a compiler transforms an expression into an abstract syntax tree and then into machine instructions, with a small original example.',
    'Prepara un itinerario immaginario di tre giorni per esplorare una città costiera a piedi. Bilancia musei, passeggiate, pasti e riposo senza citare luoghi reali.',
    'Descrivi un metodo per pianificare il consumo elettrico di un piccolo ufficio: misure, fasce di utilizzo, carichi simultanei e confronto dei dati raccolti.',
    'Write a concise design for a local document search application. Discuss indexing, incremental updates, ranking and an interface that explains why a result matched.',
]

def validate_profile(path):
    raw = Path(path).read_bytes()
    if len(raw) < 24 or raw[:4] != b'STRP':raise ValueError('Invalid learned profile header')
    version,layers,experts,slots,count = struct.unpack_from('<5I',raw,4)
    if (version,layers,experts,slots,count) != (1,48,512,24576,24576):raise ValueError('Unexpected learned profile dimensions')
    if len(raw) != 24+4*count+4*layers*experts:raise ValueError('Truncated or extended learned profile')
    pairs = [struct.unpack_from('<HH',raw,24+4*i) for i in range(count)]
    if len(set(pairs)) != count or any(l>=layers or e>=experts for l,e in pairs):raise ValueError('Invalid ranked pairs')
    table = struct.unpack_from(f'<{layers*experts}i',raw,24+4*count)
    if any(table[l*experts+e] != rank for rank,(l,e) in enumerate(pairs)):raise ValueError('Rank table mismatch')
    return dict(sha256=hashlib.sha256(raw).hexdigest(),pairs=count,bytes=len(raw)),pairs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url',required=True);parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--profile',type=Path,required=True)
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text());flags = cfg['args']
    original = Path(flags[flags.index('--expert-profile')+1]);before = hashlib.sha256(original.read_bytes()).hexdigest()
    if args.profile.exists():raise RuntimeError('Refuse to overwrite an existing candidate')
    args.profile.parent.mkdir(parents=True,exist_ok=True)
    report = dict(status='running',kind='Small synthetic routing corpus, independent prompts; no general-use speed claim',
        model=cfg['model_name'],corpus_sha256=hashlib.sha256(json.dumps(PROMPTS,ensure_ascii=False).encode()).hexdigest(),
        original_profile_sha256=before,binary_sha256=hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest(),rows=[])
    def request(path,payload):
        req = urllib.request.Request(args.url+path,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=1200) as response:return json.load(response)
    try:
        for prompt in PROMPTS:
            start = time.perf_counter()
            response = request('/v1/chat/completions',dict(model=cfg['model_name'],messages=[dict(role='user',content=prompt)],
                max_tokens=128,temperature=0,top_k=1,reasoning_effort='none'))
            choice = response['choices'][0]
            if not choice['message'].get('content') or response['usage']['completion_tokens'] <= 0:raise RuntimeError('Empty training answer')
            report['rows'].append(dict(prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                output_tokens=response['usage']['completion_tokens'],finish_reason=choice.get('finish_reason'),wall_s=time.perf_counter()-start))
            atomic_json(args.output,report)
        unloaded = request('/unload',{})
        if unloaded.get('status') not in ('unloaded','already_unloaded'):raise RuntimeError('Orderly unload did not complete: '+str(unloaded))
        details,pairs = validate_profile(args.profile)
        _,original_pairs = validate_profile(original)
        report.update(status='complete',candidate=details,profile_path=str(args.profile),
            changed_positions=sum(a!=b for a,b in zip(pairs,original_pairs)),
            training_requests=len(PROMPTS),orderly_unload=True,promotion=False)
        if hashlib.sha256(original.read_bytes()).hexdigest()!=before:raise RuntimeError('Original profile changed')
        atomic_json(args.output,report)
        print(json.dumps(report,indent=2))
    except BaseException as exc:
        report.update(status='failed',error=str(exc));atomic_json(args.output,report);raise

if __name__ == '__main__':main()
