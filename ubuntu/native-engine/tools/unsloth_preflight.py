"""Inspect the existing Unsloth environment under the shared GPU reservation.

Does not install packages, download weights, load models or train.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.gpu_lease import GpuLease
from serve.configuration import atomic_json

PROBE="""
import importlib.metadata as metadata, importlib.util, json, sys, torch, gc
packages={}
for name in ('unsloth','unsloth-zoo','transformers','trl','peft','bitsandbytes','datasets'):
    try:packages[name]=metadata.version(name)
    except metadata.PackageNotFoundError:packages[name]=None
available=torch.cuda.is_available()
checks={}
if available:
    try:
        a=torch.ones((32,32),device='cuda',dtype=torch.bfloat16)
        b=a@a;torch.cuda.synchronize()
        checks['bf16_matmul']=bool(torch.all(b==32).item())
        del a,b
    except Exception as error:checks['bf16_error']=str(error)[:1000]
    try:
        import bitsandbytes as bnb
        layer=bnb.nn.Linear4bit(64,64,bias=False,compute_dtype=torch.float16,quant_type='nf4')
        layer.weight.data.fill_(0.01);layer=layer.to('cuda')
        x=torch.ones((1,64),device='cuda',dtype=torch.float16)
        y=layer(x);torch.cuda.synchronize()
        checks['nf4_small_forward']=bool(torch.isfinite(y).all().item())
        checks['nf4_storage_dtype']=str(layer.weight.dtype)
        del layer,x,y
    except Exception as error:checks['nf4_error']=str(error)[:1000]
    gc.collect();torch.cuda.empty_cache()
try:
    import unsloth
    checks['unsloth_import']=True
except Exception as error:checks['unsloth_import']=False;checks['unsloth_error']=str(error)[:1000]
print(json.dumps(dict(python=sys.executable,torch=torch.__version__,hip=torch.version.hip,cuda=torch.version.cuda,gpu_available=available,gpu=torch.cuda.get_device_name(0) if available else None,packages=packages,checks=checks,model_loaded=False,training_validated=False)))
"""

def validate_corpus(path):
    """Explicit split and conversation IDs prevent accidental training/eval leakage."""
    splits={'train':[],'validation':[],'held_out':[]};seen=set();contents={}
    with Path(path).open(encoding='utf-8') as stream:
        for number,line in enumerate(stream,1):
            if not line.strip():continue
            row=json.loads(line)
            identity=row.get('conversation_id');split=row.get('split');messages=row.get('messages')
            if not isinstance(identity,str) or not identity or identity in seen:
                raise ValueError(f'Conversation ID missing or repeated at line {number}')
            if split not in splits or row.get('language') not in ('it','en'):
                raise ValueError(f'Explicit split and IT/EN language required at line {number}')
            if not isinstance(messages,list) or not messages or any(not isinstance(m,dict) or m.get('role') not in ('system','user','assistant') or not isinstance(m.get('content'),str) or not m['content'].strip() for m in messages):
                raise ValueError(f'Invalid text-only conversation at line {number}')
            if not any(m['role']=='assistant' for m in messages):raise ValueError(f'No assistant target at line {number}')
            digest=hashlib.sha256(json.dumps(messages,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            if digest in contents and contents[digest]!=split:raise ValueError(f'Conversation content leaks across splits at line {number}')
            contents[digest]=split
            seen.add(identity);splits[split].append(row)
    if any(not rows for rows in splits.values()):raise ValueError('Train, validation and held_out must all contain conversations')
    for split,rows in splits.items():
        if {r['language'] for r in rows}!={'it','en'}:raise ValueError(f'Both IT and EN required in {split}')
    return {split:len(rows) for split,rows in splits.items()}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',type=Path,default=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe')
    parser.add_argument('--corpus',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'data/unsloth-preflight.json')
    args=parser.parse_args()
    if not args.python.is_file():raise RuntimeError('Existing Unsloth Python not found; no duplicate environment installed')
    if args.corpus:corpus=validate_corpus(args.corpus)
    else:corpus=None
    from urllib.request import urlopen
    with urlopen('http://127.0.0.1:8088/metrics',timeout=5) as response:live=json.load(response)['live']
    if live['state']!='unloaded' or live.get('queued'):raise RuntimeError('Unload the operational model before probing the GPU runtime')
    with GpuLease(ROOT,'unsloth-preflight'):
        result=subprocess.run([str(args.python),'-c',PROBE],capture_output=True,text=True,timeout=60,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Existing runtime preflight failed: '+result.stderr[-2000:])
    lines=result.stdout.splitlines()
    report=next((json.loads(line) for line in reversed(lines) if line.startswith('{')),None)
    if not report:raise RuntimeError('No valid preflight report')
    report.update(checked_at=time.time(),kind='unsloth_runtime_preflight',corpus=corpus,
                  weights_created=False,limitations='Tiny BF16/NF4 checks validate components, not a full model load, training or quality')
    if args.corpus:report['corpus_sha256']=hashlib.sha256(args.corpus.read_bytes()).hexdigest()
    atomic_json(args.output,report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
