"""Reuse the dashboard MCP hub for OpenAI-compatible backends."""
import copy
import json


def chat_with_tools(manager, hub, payload, cancel):
    tools = hub.template_tools()
    selected=payload.get('strata_tools')
    if selected is not None:
        if not isinstance(selected,list) or any(not isinstance(name,str) for name in selected):raise ValueError('Selezione strumenti non valida')
        tools=[t for t in tools if t['name'] in selected]
    if payload.get('strata_web') is not True:
        tools=[t for t in tools if not t['name'].endswith(('__search_web','__read_web_page','__weather_forecast'))]
    own = payload.get('tools') or []
    names = {t.get('function', {}).get('name') for t in own}
    tools = [t for t in tools if t['name'] not in names]
    available = {t['name'] for t in tools}
    if payload.get('strata_web') is True:
        from serve.weather_intent import intent,run
        weather=next((name for name in available if name.endswith('__weather_forecast')),None)
        args=intent(payload['messages']) if weather else None
        if args:
            yield from run(hub,weather,args,manager.status()['public_model'],cancel,english=str(payload.get('strata_locale','')).startswith('en'))
            return
    if hasattr(manager,'status'):
        status=manager.status()
        if status.get('mode')=='safetensors' and status.get('capabilities',{}).get('tool_calling') is False:
            tools=[];available=set()
    messages = copy.deepcopy(payload['messages'])
    usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    budget = payload.get('max_tokens', 2048)
    for round_index in range(int(hub.settings['max_rounds']) + 1):
        if cancel.is_set(): return
        request = {**payload, 'messages': messages, 'stream': bool(payload.get('stream',False)),
                   'max_tokens': budget, 'tools': own + [{'type': 'function', 'function': t} for t in tools]}
        if round_index: request.pop('tool_choice', None)
        if round_index == int(hub.settings['max_rounds']):
            request['tools'] = own
            request['messages'] = messages + [{'role':'user','content':'Return the final answer using the tool results already obtained. Explain any missing information; do not request more tools.'}]
            request['chat_template_kwargs'] = {**(request.get('chat_template_kwargs') or {}), 'enable_thinking':False}
        early_stream=request['stream']
        if early_stream:
            packets=[];last_usage=None;last_timings=None
            for packet in manager.chat(request,cancel):
                if packet.get('usage'):last_usage=packet['usage']
                if packet.get('timings'):last_timings=packet['timings']
                choices=packet.get('choices') or []
                if not choices:continue
                packets.append(packet)
                delta=choices[0].get('delta') or {}
                if delta.get('content') or delta.get('reasoning_content'):
                    yield {**packet,'choices':[{**choices[0],'finish_reason':None}],'usage':None}
            if not packets:return
            from serve.server import openai_collect
            packets[-1]={**packets[-1],'usage':last_usage or {'prompt_tokens':None,'completion_tokens':None,'total_tokens':None}}
            if last_timings:packets[-1]['timings']=last_timings
            response=openai_collect(packets)
        else:
            responses = list(manager.chat(request, cancel))
            response = responses[0] if responses else None
        if response is None: return
        for key in usage: usage[key] += (response.get('usage') or {}).get(key) or 0
        budget -= (response.get('usage') or {}).get('completion_tokens') or 0
        choice = response['choices'][0]
        message = choice['message']
        calls = message.get('tool_calls') or []
        managed = calls and all(c.get('function', {}).get('name') in available for c in calls)
        base = {k: response[k] for k in ('id', 'created', 'model')}
        base['object'] = 'chat.completion.chunk'
        def chunk(delta, finish=None, **extra):
            return {**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}], **extra}
        if message.get('content') and not early_stream: yield chunk({'content': message['content']})
        if message.get('reasoning_content') and not early_stream: yield chunk({'reasoning_content': message['reasoning_content']})
        if not managed:
            if calls: yield chunk({'tool_calls': [{**c, 'index': i} for i, c in enumerate(calls)]})
            yield chunk({}, choice.get('finish_reason') or 'stop', usage=usage,
                        **({'timings': response['timings']} if response.get('timings') else {}))
            return
        if round_index >= int(hub.settings['max_rounds']) or budget <= 0:
            yield chunk({}, 'length', usage=usage, strata_mcp={'event': 'limit', 'max_rounds': hub.settings['max_rounds']})
            return
        messages.append(message)
        for call in calls:
            if cancel.is_set(): return
            fn = call['function']; identity = call.get('id') or f'call_{round_index}_{len(messages)}'
            call['id'] = identity
            yield chunk({}, strata_mcp={'event': 'call', 'id': identity, 'name': fn['name'],
                                        'arguments': fn.get('arguments', '{}'), 'round': round_index + 1})
            arguments = fn.get('arguments') or {}
            for _ in range(2):
                if isinstance(arguments,str):arguments=json.loads(arguments)
            if not isinstance(arguments, dict): raise ValueError('Argomenti dello strumento non validi')
            fn['arguments']=json.dumps(arguments,ensure_ascii=False)
            result = hub.call(fn['name'], arguments, cancel)
            yield chunk({}, strata_mcp={'event': 'result', 'id': identity,
                                        **{k: result[k] for k in ('ok', 'text', 'chars', 'truncated', 'ms')}})
            messages.append({'role': 'tool', 'tool_call_id': identity, 'content': result['text']})
