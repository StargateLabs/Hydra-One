"""Offline CPU Safetensors cross-encoder in the selected document environment."""
import json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def run(payload):
    from serve.document_reranker import model,ranked
    if payload.get('action')!='rerank':raise ValueError('Unsupported action')
    rows=payload.get('matches',[]);query=payload.get('query')
    if not isinstance(query,str) or not 1<=len(query)<=4000 or not isinstance(rows,list) or len(rows)>16 or any(not isinstance(r,dict) or not isinstance(r.get('text'),str) or len(r['text'])>16000 for r in rows):raise ValueError('Invalid reranker input')
    prepared=model(ROOT,verify=True)
    import psutil
    if psutil.virtual_memory().available<prepared['bytes']*4+512*1024**2:raise ValueError('Insufficient RAM for CPU reranker')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1')
    import torch
    from transformers import AutoTokenizer,AutoModelForSequenceClassification
    torch.set_num_threads(2);started=time.monotonic()
    tokenizer=AutoTokenizer.from_pretrained(prepared['folder'],local_files_only=True,trust_remote_code=False)
    encoder=AutoModelForSequenceClassification.from_pretrained(prepared['folder'],local_files_only=True,trust_remote_code=False,use_safetensors=True).eval()
    scores=[]
    for offset in range(0,len(rows),4):
        batch=rows[offset:offset+4];features=tokenizer([query]*len(batch),[r['text'] for r in batch],padding=True,truncation=True,max_length=512,return_tensors='pt')
        with torch.inference_mode():scores.extend(encoder(**features).logits.flatten().tolist())
    return {'matches':ranked(rows,scores),'reranker':prepared['name'],'rerank_seconds':round(time.monotonic()-started,3),'rerank_scope':'Local CPU cross-encoder on retrieved candidates; raw logits, not probabilities; 512-token pair limit'}
if __name__=='__main__':
    try:print('STARGATE_RESULT:'+json.dumps(run(json.loads(sys.stdin.buffer.read(2*1024*1024+1)))),flush=True)
    except Exception as error:print('STARGATE_RESULT:'+json.dumps({'error':str(error)}),flush=True);raise SystemExit(1)
