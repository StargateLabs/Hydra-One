"""Isolated System One-shaped question adapter over HYDRA native CPU scoring.

Never contacts or modifies System One. Uses Qwen's own tokenizer/likelihoods,
not Colibri's semantic boundary. Comparability and calibration are unverified.
"""
import json,math
def execute_bridge(lab,body):
 if not isinstance(body,dict) or set(body)-{'state','questions','normalize','prefix','pin_state','cache_slot'}:raise ValueError('BRIDGE_SCHEMA: bounded System One-shaped questions required')
 if body.get('pin_state') is True or body.get('cache_slot') is not None:raise ValueError('BRIDGE_CACHE_UNSUPPORTED: native CPU scorer resets cache per alternative')
 if len(json.dumps(body,ensure_ascii=False))>8000 or not isinstance(body.get('questions'),dict) or not 1<=len(body['questions'])<=4:raise ValueError('BRIDGE_BUDGET:1..4 questions,8000 characters total')
 from serve.hydra_lab_modules import load
 contract=load('system_one_semantics_contract_lab');plan=contract.lab_llm_plan(body)
 for question in plan['questions']:
  if not 2<=len(question['options'])<=4:raise ValueError('BRIDGE_OPTIONS:2..4 alternatives per native question')
 rendered={row['id']:row for row in contract.lab_render(body)};native=[];logprobs={}
 for question in plan['questions']:
  formatted=rendered[question['id']]
  result=lab.prefix_score(dict(prefix_text=formatted['prefix'],alternatives=[dict(id=option,text=text) for option,text in zip(question['options'],formatted['continuations'])],separator='exact',normalize=plan['normalize']))
  native.append(dict(question_id=question['id'],result=result))
  if result.get('status')!='complete':raise ValueError('BRIDGE_NATIVE_SCORING_INCOMPLETE')
  values={}
  for alternative in result['alternatives']:
   tokens=[token['logprob'] for token in alternative.get('tokens',[])]
   if not tokens or any(type(value) not in (int,float) or not math.isfinite(value) for value in tokens):raise ValueError('BRIDGE_NATIVE_TOKEN_LOGPROBS_REQUIRED')
   values[alternative['id']]=tokens
  if set(values)!=set(question['options']):raise ValueError('BRIDGE_ALTERNATIVE_IDENTITY_MISMATCH')
  logprobs[question['id']]=values
 answers=contract.lab_reply(body,logprobs)
 return dict(status='complete',answers=answers,native_calls=len(native),native_results=native,compatibility=dict(schema='hydra.isolated-system-one-shaped.v1',model=lab.profile['model'],model_sha256=lab.profile['model_sha256'],tokenizer='GGUF model tokenizer; see native per-call provenance',template='System One-shaped question formatter; raw-prefix-continuation-v13 native exact boundary',system_one_contacted=False,system_one_parity='NOT_VERIFIED',colibri_boundary='NOT_USED',probabilities='normalized native token likelihoods; calibration NOT_VERIFIED',score_index_origin=0,cache='reset per native alternative; no pinned recurrent state'))
