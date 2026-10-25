"""Exact-prefix native CPU scoring, separate from the fixture-only contract lab."""
import hashlib,time
def prefix_request(body):
 if not isinstance(body,dict) or set(body)-{'prefix_text','alternatives','separator','normalize'}:raise ValueError('PREFIX_SCHEMA: explicit prefix and alternatives required')
 prefix=body.get('prefix_text');alternatives=body.get('alternatives');separator=body.get('separator','exact')
 if not isinstance(prefix,str) or not prefix or len(prefix)>4096 or separator not in ('exact','space'):raise ValueError('PREFIX_BUDGET_OR_SEPARATOR')
 if not isinstance(alternatives,list) or not 1<=len(alternatives)<=4:raise ValueError('PREFIX_ALTERNATIVES:1..4 required')
 seen=set();converted=[]
 for alternative in alternatives:
  if not isinstance(alternative,dict) or set(alternative)!={'id','text'} or not isinstance(alternative['id'],str) or not 1<=len(alternative['id'])<=128 or alternative['id'] in seen or not isinstance(alternative['text'],str) or not alternative['text'] or len(alternative['text'])>1024:raise ValueError('PREFIX_ALTERNATIVE_IDENTITY_OR_BUDGET')
  text=(' ' if separator=='space' else '')+alternative['text'];text.encode('utf-8',errors='strict')
  seen.add(alternative['id']);converted.append(dict(id=alternative['id'],text=text))
 raw=prefix.encode('utf-8',errors='strict')
 request=dict(backend='llama.cpp-cpu-capi',model='Qwen3-0.6B-Q8_0',document='',question='',prefix_text=prefix,alternatives=converted,mode='continuation_logprobs',normalize=body.get('normalize','sum'),template='raw-prefix-continuation-v13',deadline=time.monotonic()+40,repeat=1)
 if request['normalize'] not in ('sum','mean'):raise ValueError('PREFIX_NORMALIZE')
 identity=dict(prefix_utf8_hex=raw.hex(),prefix_sha256=hashlib.sha256(raw).hexdigest(),separator=separator,normalization='NONE; exact Unicode/UTF8 preserved',boundary='native full-tokenization must start with exact prefix token IDs; otherwise unscorable_boundary',context_budget_tokens=128,full_budget_tokens=256)
 return request,identity
def execute_prefix(lab,body):
 request,identity=prefix_request(body)
 from serve.hydra_lab_modules import load
 scoring=load('decision_scoring')
 from serve.hydra_scoring_runtime import backend as scoring_backend
 backend=scoring_backend(lab,scoring)
 result=scoring.score_alternatives(request,backend);result['prefix_identity']=identity;result['model_identity']=dict(model=lab.profile['model'],sha256=lab.profile['model_sha256'],colibri_parity='NOT_VERIFIED; different model/tokenizer');return result
