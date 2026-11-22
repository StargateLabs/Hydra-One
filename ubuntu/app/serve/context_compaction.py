"""Manual, bounded extractive context reduction; original history is never edited.

This is an excerpt generator, not a semantic/model summary. System messages,
recent turns, multimodal content, and complete tool call/result records remain
byte-for-byte equivalent JSON values. Every shortened message is disclosed.
"""
import hashlib
import json

def prepare(payload,root=None):
    if not isinstance(payload,dict):raise ValueError('Richiesta non valida.')
    messages=payload.get('messages')
    if not isinstance(messages,list) or len(messages)>2000:raise ValueError('Da 1 a 2000 messaggi richiesti.')
    encoded=json.dumps(messages,ensure_ascii=False,separators=(',',':'))
    if not messages or len(encoded)>2000000:raise ValueError('Contesto vuoto o oltre 2 milioni di caratteri.')
    keep=payload.get('keep_recent_turns',4)
    budget=payload.get('max_summary_chars',6000)
    if not isinstance(keep,int) or isinstance(keep,bool) or not 2<=keep<=20:raise ValueError('Conserva da 2 a 20 turni recenti.')
    if not isinstance(budget,int) or isinstance(budget,bool) or not 1000<=budget<=20000:raise ValueError('Budget estratti da 1000 a 20000 caratteri.')
    for m in messages:
        if not isinstance(m,dict) or m.get('role') not in ('system','developer','user','assistant','tool'):
            raise ValueError('Ruolo messaggio non valido.')
    users=[i for i,m in enumerate(messages) if m['role']=='user']
    cutoff=users[-keep] if len(users)>keep else 0
    analysis=None
    if root is not None:
        from serve.open_webui_runtime import status,context
        if status(root)['ready']:
            analysis=context(root,messages)
            cutoff=min(cutoff,max(0,analysis['boundary']))
    eligible=[i for i,m in enumerate(messages[:cutoff]) if m['role'] in ('user','assistant')
              and isinstance(m.get('content'),str) and len(m['content'])>500
              and not m.get('tool_calls') and not m.get('function_call')]
    # Tool-adjacent assistant records are part of a tool exchange even when
    # they contain no calls themselves. Preserve the whole originating turn.
    protected=set()
    for start,end in zip(users,users[1:]+[len(messages)]):
        if any(m.get('tool_calls') or m['role']=='tool' for m in messages[start:end]):
            protected.update(range(start,end))
    eligible=[i for i in eligible if i not in protected]
    eligible=eligible[-max(1,budget//400):]
    allowance=max(200,min(1100,budget//max(1,len(eligible))-100))
    changes=[]
    for i in eligible:
        original=messages[i]['content']
        head=allowance*2//3;tail=allowance-head
        content=original[:head]+'\n[Historical excerpt: middle omitted; original retained in this conversation.]\n'+original[-tail:]
        if len(content)>=len(original):continue
        changes.append({'index':i,'original':messages[i],'replacement':{**messages[i],'content':content},
                        'removed_characters':len(original)-len(content)})
    after=list(messages)
    for change in changes:after[change['index']]=change['replacement']
    return {'kind':'extractive','context_analysis':analysis,'changes':changes,'before_characters':len(encoded),
            'after_characters':len(json.dumps(after,ensure_ascii=False,separators=(',',':'))),
            'source_sha256':hashlib.sha256(encoded.encode()).hexdigest(),
            'recent_turns_preserved':keep,'original_history_preserved':True,
            'disclosure':'Estratti iniziali e finali, non riassunto semantico. Il testo centrale viene omesso dal prossimo prompt; la conversazione originale resta completa.'}
