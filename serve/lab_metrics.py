"""Statistics from observed samples; unknown values never become zero."""
import math,statistics
METRICS=('decode_tok_s','prefill_tok_s','wall_tok_s','wall_s','ttft_s','generation_ms')
GENERATION_SCOPE='model.generate_including_prefill'
def valid_number(value):return type(value) in (int,float) and math.isfinite(value) and value>0

def measured_series(rows,limit=100):
 result=[]
 for row in rows:
  if not isinstance(row,dict) or row.get('warmup') is not False or row.get('error'):continue
  sample={metric:row.get(metric) if valid_number(row.get(metric)) else None for metric in METRICS}
  sample['timing_scope']=row.get('timing_scope') if row.get('timing_scope')==GENERATION_SCOPE else None
  if sample['timing_scope'] is None:sample['generation_ms']=None
  count=row.get('output_tokens');sample['output_tokens']=count if type(count) is int and count>0 else None
  if sample['wall_tok_s'] is None and sample['output_tokens'] is not None and sample['wall_s'] is not None:sample['wall_tok_s']=count/sample['wall_s']
  result.append(sample)
  if len(result)>=limit:break
 return result

def summarize(rows):
 measured=[row for row in rows if row.get('warmup') is False and not row.get('error')]
 result={}
 for metric in METRICS:
  if metric=='generation_ms' and any(row.get('timing_scope')!=GENERATION_SCOPE for row in measured):continue
  values=[row.get(metric) for row in measured]
  if not values or not all(valid_number(value) for value in values):continue
  item={'count':len(values),'min':min(values),'max':max(values),'median':statistics.median(values),'mean':statistics.mean(values),'sample_stddev':statistics.stdev(values) if len(values)>1 else None,'p95':None}
  if len(values)>=20:item['p95']=statistics.quantiles(values,n=100,method='inclusive')[94]
  result[metric]=item
 return result
