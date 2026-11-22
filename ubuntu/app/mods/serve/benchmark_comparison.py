"""Compare persisted observations without deriving decode from HTTP/model time."""
import hashlib,json,re,statistics
from pathlib import Path
from serve.lab_metrics import summarize,valid_number,GENERATION_SCOPE

SCOPES={'wall_s':'HTTP request through response completion','wall_tok_s':'Output tokens / HTTP request wall time','ttft_s':'HTTP request to first nonempty content event','generation_ms':GENERATION_SCOPE,'decode_tok_s':'Backend-reported decode only','prefill_tok_s':'Backend-reported prefill only'}

def model_fingerprint(model):
 """Hash local checkpoint content once per benchmark, never infer from alias."""
 path=Path(model).resolve();files=([path] if path.is_file() else sorted(p for p in path.iterdir() if p.is_file() and (p.suffix in ('.safetensors','.gguf') or p.name in ('config.json','tokenizer.json','tokenizer_config.json','generation_config.json'))))
 if not files or not any(p.suffix in ('.gguf','.safetensors') for p in files):return None
 digest=hashlib.sha256()
 for item in files:
  digest.update(item.name.encode());digest.update(str(item.stat().st_size).encode())
  with item.open('rb') as stream:
   for chunk in iter(lambda:stream.read(4*1024**2),b''):digest.update(chunk)
 return digest.hexdigest()

def compare_reports(root,sources):
 if not isinstance(sources,list) or not 2<=len(sources)<=8 or len(set(sources))!=len(sources) or any(not isinstance(source,str) for source in sources):raise ValueError('Choose 2..8 distinct benchmark reports')
 folder=(Path(root)/'data/benchmark-checks').resolve();rows=[]
 for source in sources:
  path=(folder/source).resolve()
  if path.parent!=folder or path.suffix!='.json':raise ValueError('Invalid benchmark report path')
  report=json.loads(path.read_text(encoding='utf-8-sig'));protocol=report.get('protocol',{})
  if report.get('status')!='complete':raise ValueError('Only completed benchmark reports can be compared')
  runs=protocol.get('runs');warmup=protocol.get('warmup');tokens=protocol.get('tokens')
  if any(type(value) is not int or value<0 for value in (runs,warmup,tokens)) or runs<1 or tokens<1:raise ValueError('Invalid benchmark protocol')
  arms=report.get('runs',[])
  if not arms:raise ValueError('Missing measured benchmark arms')
  for arm in arms:
   samples=arm.get('rows',[]);measured=[sample for sample in samples if sample.get('warmup') is False];warm=[sample for sample in samples if sample.get('warmup') is True]
   if len(measured)!=runs or len(warm)!=warmup or len(samples)!=runs+warmup or any(sample.get('error') or type(sample.get('output_tokens')) is not int or not 0<sample['output_tokens']<=tokens for sample in samples):raise ValueError('Incomplete or invalid benchmark samples')
   observed=[]
   for sample in samples:
    sample=dict(sample)
    if valid_number(sample.get('wall_s')):sample['wall_tok_s']=sample['output_tokens']/sample['wall_s']
    observed.append(sample)
   config=protocol.get('configuration') or {}
   rows.append(dict(source=source,arm=arm.get('arm'),model=arm.get('public_model'),model_file=report.get('model_file'),backend=report.get('backend'),protocol=protocol,configuration=config,summary=summarize(observed),device=config.get('device'),fit_mode=config.get('fit_mode'),stream=protocol.get('stream'),output_tokens=[sample['output_tokens'] for sample in measured],verification_fixture=report.get('verification_fixture',False)))
 reasons=[];first=rows[0]
 for row in rows:
  protocol=row['protocol']
  for key in ('prompt_sha256','model_sha256'):
   value=protocol.get(key)
   if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):reasons.append('Missing verified '+key)
   elif value!=first['protocol'].get(key):reasons.append('Different '+key)
  if type(protocol.get('stream')) is not bool:reasons.append('Stream mode was not recorded')
  for key in ('tokens','runs','warmup','cache_prompt','output_policy','generation_parameters'):
   if protocol.get(key)!=first['protocol'].get(key):reasons.append('Different protocol '+key)
  # Actual early endings can differ between modes. Retain observations but do
  # not attribute that different amount of work to device/stream speed.
  if row['output_tokens']!=first['output_tokens']:reasons.append('Different measured output token counts')
  if not row['device'] or not row['fit_mode']:reasons.append('Missing measured device or resident/streaming mode')
  if row['backend']!=first['backend']:reasons.append('Different backend implementations')
 comparable=not reasons;metrics={}
 if comparable:
  for name,label in SCOPES.items():
   if not all(name in row['summary'] for row in rows):continue
   values=[row['summary'][name]['median'] for row in rows]
   metrics[name]=dict(scope=label,medians=values,ratios=[value/values[0] for value in values],ratio_scope='Observed median / first report median; separate runs, not causal ABBA')
 return dict(rows=rows,comparable=comparable,reasons=list(dict.fromkeys(reasons)),metrics=metrics,scope='Recorded local observations; model, HTTP, prefill and decode remain distinct',quality_claim=False)
