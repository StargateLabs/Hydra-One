"""Run original Soup planning formulas offline; never imports torch or touches GPU."""
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'serve/vendor/soup/src'))
from soup_cli.utils.layer_stream import build_stream_plan,estimate_stream_peak_vram,stream_arch_of
from dataclasses import asdict

def plan(payload):
 folder=Path(payload['model']);config=json.loads((folder/'config.json').read_text());arch=stream_arch_of(SimpleNamespace(**config))
 sizes={};shapes={}
 for file in folder.glob('*.safetensors'):
  with file.open('rb') as stream:
   length=struct.unpack('<Q',stream.read(8))[0]
   if length>16*1024**2:raise ValueError('Safetensors header exceeds limit')
   header=json.loads(stream.read(length))
  for name,value in header.items():
   if name=='__metadata__':continue
   dims=value['shape'];size=math.prod(dims)*2 # explicit streaming f16, not NF4
   sizes[name]=size;shapes[name]=dims
 layers={}
 for name,size in sizes.items():
  match=re.match(r'model\.layers\.(\d+)\.',name)
  if match:layers[match[1]]=layers.get(match[1],0)+size
 if not layers:raise ValueError('Decoder layout unsupported by planning bridge')
 n=config['num_hidden_layers']
 if len(layers)!=n:raise ValueError('Missing decoder layers')
 layer=max(layers.values());store=sum(layers.values());emb=sizes.get('model.embed_tokens.weight',0);head=sizes.get('lm_head.weight',0);large=max(emb,head);resident=sum(sizes.values())-store-emb-head
 adapters=sum(payload['rank']*sum(dims) for name,dims in shapes.items() if len(dims)==2 and name.endswith(('q_proj.weight','v_proj.weight')))
 stream=build_stream_plan(arch=arch,n_layers=n,layer_bytes=layer,embed_bytes=resident,available_ram_bytes=payload['available_ram_bytes'],total_ram_bytes=payload['total_ram_bytes'],pinned_limit_bytes=None,buffers=2,store_bytes=store,large_store_bytes=emb+head,large_buffer_bytes=large,stream_pin=False)
 peak=estimate_stream_peak_vram(layer_bytes=layer,buffers=2,extras_bytes=resident,adapter_params=adapters,vocab_size=config['vocab_size'],hidden_size=config['hidden_size'],intermediate_size=config['intermediate_size'],n_layers=n,seq_len=payload['length'],batch_size=1,dtype='float16',large_layer_bytes=large)
 assert 'torch' not in sys.modules
 return {'source':'Soup 0.75.0 original planner','revision':'61e8c2bf354393cea85002401d0bde803b48f614','scope':'Estimate only; f16 streaming, no pinning and no GPU execution; not calibrated on AMD','plan':asdict(stream),'predicted_allocator_bytes':peak,'adapter_parameters':adapters,'runtime_enabled':False}
if __name__=='__main__':
 os.environ.update(CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')
 print(json.dumps(plan(json.load(sys.stdin))))
