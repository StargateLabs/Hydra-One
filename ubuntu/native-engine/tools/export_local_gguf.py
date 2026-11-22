"""Offline Safetensors to GGUF using installed Unsloth llama.cpp converter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.safetensors_runtime import inspect_model
from tools.gguf_reader import GGUFFile

def convert(model,output,kind='f16'):
    model=Path(model).resolve(strict=True);output=Path(output).resolve()
    if kind not in ('f16','bf16','q8_0'):raise ValueError('Unsupported export type')
    if output.suffix!='.gguf' or not output.is_relative_to(ROOT/'output') or output.exists():raise ValueError('Choose a new GGUF file inside project output')
    info=inspect_model(model)
    converter=Path.home()/'.unsloth/llama.cpp/convert_hf_to_gguf.py';python=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
    if not converter.is_file() or not python.is_file():raise ValueError('Installed converter or Python unavailable')
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<info['bytes']*2+1024**3:raise ValueError('Insufficient disk space for export')
    partial=output.parent/(uuid.uuid4().hex+'.partial.gguf');log=output.with_suffix('.conversion.log')
    env=dict(os.environ,CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    try:
        with log.open('xb') as stream:
            result=subprocess.run([str(python),str(converter),str(model),'--outfile',str(partial),'--outtype',kind],env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=1800)
        if result.returncode:raise RuntimeError('Conversion failed; inspect '+str(log))
        gguf=GGUFFile(partial)
        if not gguf.tensors or not gguf.metadata.get('general.architecture'):raise ValueError('Export structure incomplete')
        size=partial.stat().st_size
        if any(t.expected_bytes() is None or t.offset+t.expected_bytes()+gguf.data_start>size for t in gguf.tensors):raise ValueError('Export tensors exceed file bounds')
        with partial.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
        partial.rename(output)
        report={'status':'complete','device':'cpu','source':str(model),'output':str(output),'type':kind,'architecture':gguf.metadata['general.architecture'],'tensors':len(gguf.tensors),'sha256':digest,'bytes':size,'runtime_loaded':False}
        output.with_suffix('.export.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
    finally:
        if partial.exists():partial.unlink()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--output',required=True);parser.add_argument('--type',choices=['f16','bf16','q8_0'],default='f16');args=parser.parse_args();print(json.dumps(convert(args.model,args.output,args.type),indent=2))
