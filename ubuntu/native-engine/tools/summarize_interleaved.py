"""Validate fresh paired requests in one engine; never turn mixed settings into a record."""
import hashlib,json,math,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def summarize(stamp):
 label=f'{stamp}-iq3-memory-minp70-interleaved'
 path=ROOT/f'output/verification/{label}-results.json'
 r=json.loads(path.read_text());cfg=json.loads((ROOT/f'output/verification/{label}.json').read_text());margin=json.loads((ROOT/f'output/verification/{label}-startup-margin.json').read_text())
 def require(ok,msg):
  if not ok:raise RuntimeError(msg)
 require(r['status']=='complete' and len(r['rows'])==22,'Incomplete experiment')
 require(r['protocol']==dict(warmup=5,runs=6,tokens=256,paragraphs=24,prompt_set='iq3-minp-interleaved-v1',interleaved=True,settings=[0.5,0.7],order='alternating AB/BA pairs',prompt_cache=False),'Wrong protocol')
 require(margin['before_prompts'] is True and margin['vram_free_mib']>=1536,'Unsafe startup margin')
 require(r['binary_sha256']==hashlib.sha256(Path(cfg['exe']).read_bytes()).hexdigest(),'Wrong binary')
 for flag in ('--prompt-cache','--conversation-cache-mib'):
  require(cfg['args'].count(flag)==1 and cfg['args'][cfg['args'].index(flag)+1]=='0','Cache enabled')
 for i,row in enumerate(r['rows']):
  pair=i//2;expected=([0.5,0.7] if pair%2==0 else [0.7,0.5])[i%2]
  require(row['pair']==pair and row['order']==i%2 and row['spec_min_p']==expected and row['warmup']==(pair<5),'Wrong order')
  require(row['reused']==0 and row['output_tokens']==row['generated']==256,'Cached prompt or incomplete output')
  require(all(isinstance(row[k],(int,float)) and math.isfinite(row[k]) and row[k]>0 for k in ('decode_tok_s','prefill_tok_s','wall_s')),'Invalid timing')
  if i%2:require(row['prompt_sha256']==r['rows'][i-1]['prompt_sha256'],'Unpaired prompt')
 rows=r['rows'][10:];a=[x['decode_tok_s'] for x in rows if x['spec_min_p']==0.5];b=[x['decode_tok_s'] for x in rows if x['spec_min_p']==0.7]
 deltas=[]
 for pair in range(5,11):
  rates={x['spec_min_p']:x['decode_tok_s'] for x in rows if x['pair']==pair};deltas.append((rates[0.7]/rates[0.5]-1)*100)
 result=dict(status='complete',stamp=stamp,model=r['engine']['model'],control=statistics.median(a),candidate=statistics.median(b),change_percent=(statistics.median(b)/statistics.median(a)-1)*100,median_paired_change_percent=statistics.median(deltas),paired_changes_percent=deltas,candidate_wins=sum(x>0 for x in deltas),pairs=6,promotion=False,source=path.relative_to(ROOT).as_posix(),limitations='One paired same-instance confirmation; speedup below the 3% calibration threshold. No promotion.',binary_sha256=r['binary_sha256'],expert_slots=r['engine']['expert_slots'],measured_at=r['started_at'],protocol=r['protocol'])
 result['pooled']={}
 for metric in ('decode_tok_s','prefill_tok_s','wall_s','wall_tok_s'):
  control=statistics.median(x[metric] for x in rows if x['spec_min_p']==0.5);candidate=statistics.median(x[metric] for x in rows if x['spec_min_p']==0.7)
  result['pooled'][metric]=dict(control=control,candidate=candidate,change_percent=(candidate/control-1)*100)
 (ROOT/f'output/verification/{stamp}-minp70-interleaved-summary.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
 import sys
 print(json.dumps(summarize(sys.argv[1]),indent=2))
