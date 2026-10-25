"""Recovered local choice formatter; never contacts System One or claims parity."""
import json
import math


def lab_llm_plan(body):
    if not isinstance(body,dict) or set(body)-{'state','questions','normalize','prefix','pin_state','cache_slot'}:
        raise ValueError('QUESTION_SCHEMA')
    if body.get('pin_state') is True or body.get('cache_slot') is not None:raise ValueError('CACHE_UNSUPPORTED')
    state=body.get('state');questions=body.get('questions');normalize=body.get('normalize','sum')
    if not isinstance(state,str) or not 1<=len(state)<=4096 or not isinstance(questions,dict) or not 1<=len(questions)<=4 or normalize not in ('sum','mean'):
        raise ValueError('QUESTION_BUDGET')
    if len(json.dumps(body))>8000:raise ValueError('QUESTION_BYTES')
    rows=[]
    for identity,question in questions.items():
        if not isinstance(identity,str) or not 1<=len(identity)<=128 or not isinstance(question,dict) or set(question)-{'type','instructions','criteria'} or question.get('type')!='choice':raise ValueError('CHOICE_QUESTION_REQUIRED')
        criteria=question.get('criteria');instructions=question.get('instructions')
        if not isinstance(instructions,str) or not 1<=len(instructions)<=1024 or not isinstance(criteria,dict) or not 2<=len(criteria)<=4 or any(not isinstance(k,str) or not 1<=len(k)<=128 or not isinstance(v,str) or len(v)>1024 for k,v in criteria.items()):raise ValueError('CHOICE_CRITERIA')
        rows.append(dict(id=identity,options=list(criteria),instructions=instructions,criteria=criteria))
    return dict(questions=rows,normalize=normalize)


def lab_render(body):
    plan=lab_llm_plan(body);prefix=body.get('prefix','')
    if not isinstance(prefix,str) or len(prefix)>1024:raise ValueError('PREFIX_BUDGET')
    return [dict(id=row['id'],prefix=prefix+body['state']+'\n'+row['instructions']+'\nAnswer:',
                 continuations=[' '+option for option in row['options']]) for row in plan['questions']]


def lab_reply(body,logprobs):
    plan=lab_llm_plan(body);answers={}
    for row in plan['questions']:
        values=logprobs.get(row['id'],{})
        if set(values)!=set(row['options']):raise ValueError('CHOICE_SCORE_IDENTITY')
        scores={}
        for option,tokens in values.items():
            if not isinstance(tokens,list) or not tokens or any(type(v) not in (int,float) or not math.isfinite(v) for v in tokens):raise ValueError('FINITE_NATIVE_SCORES_REQUIRED')
            scores[option]=sum(tokens)/(len(tokens) if plan['normalize']=='mean' else 1)
        maximum=max(scores.values());weights={k:math.exp(v-maximum) for k,v in scores.items()};total=sum(weights.values())
        answers[row['id']]=dict(choice=max(scores,key=scores.get),scores=scores,
            probabilities={k:v/total for k,v in weights.items()},calibrated=False)
    return answers
