"""Offline audit of immediate scratch accesses in the failed gfx1100 binary."""
import json
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def scratch_accesses(body,declared):
 rows=[]
 for direction,width,args in re.findall(r'\bscratch_(load|store)_b(\d+)\s+([^\n]+)',body):
  args=args.split('//',1)[0].strip();found=re.search(r'offset:(\d+)',args);offset=int(found[1]) if found else 0
  addressing=args.split(' offset:',1)[0];immediate=bool(re.fullmatch(r'off, .+, off',addressing) if direction=='store' else re.fullmatch(r'.+, off, off',addressing))
  size=int(width)//8;rows.append({'direction':direction,'width_bytes':size,'offset':offset,'end':offset+size,'immediate_address':immediate})
 return {'instructions':len(rows),'max_immediate_end':max((r['end'] for r in rows if r['immediate_address']),default=0),'dynamic_address_count':sum(not r['immediate_address'] for r in rows),'all_immediate_accesses_within_declared':all(r['end']<=declared for r in rows if r['immediate_address'])}
def audit():
 metadata=json.loads((ROOT/'output/verification/hc-compiled-resources.json').read_text());kernels=[r for r in metadata['kernels'] if r['direction']=='down'];symbols=','.join(r['symbol'] for r in kernels)
 tool=ROOT/'.rocm-win/Lib/site-packages/_rocm_sdk_devel/lib/llvm/bin/llvm-objdump.exe';binary=ROOT/'build-hc-small-window-01403/strata.exe.22.hip-amdgcn-amd-amdhsa--gfx1100'
 disassembly=subprocess.check_output([str(tool),'--disassemble-symbols='+symbols,'--no-show-raw-insn',str(binary)],text=True)
 blocks=re.split(r'^\w+ <([^>]+)>:\s*$',disassembly,flags=re.M);mapping=dict(zip(blocks[1::2],blocks[2::2]));rows=[]
 for kernel in kernels:
  if kernel['symbol'] not in mapping:raise ValueError('Compiled kernel missing from disassembly')
  rows.append({'tokens':kernel['tokens'],'declared_private_bytes':kernel['private_segment_fixed_size'],**scratch_accesses(mapping[kernel['symbol']],kernel['private_segment_fixed_size'])})
 return {'scope':'Offline compiled immediate-address audit; no GPU execution or runtime pointer validation','binary_sha256':metadata['binary_sha256'],'kernels':rows,'root_cause_confirmed':False,'finding':'Immediate scratch bounds alone do not validate graph lifetime or runtime scratch allocation'}
if __name__=='__main__':
 report=audit();(ROOT/'output/verification/hc-scratch-bounds.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
