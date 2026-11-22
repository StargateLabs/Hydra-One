"""Reuse the dashboard MCP hub for OpenAI-compatible backends.

With many selected tools, the model receives three compact tools - search,
describe and call - instead of every full JSON schema.  The selected set is
still the allowlist enforced by `call`, so this saves prompt tokens without
widening what the model may run.
"""
import copy
import json
import time

COMPACT_THRESHOLD = 12
COMPACT_NAMES = {'strata_mcp_search', 'strata_mcp_describe', 'strata_mcp_call'}


def compact_tools():
    return [
        {'name': 'strata_mcp_search',
         'description': 'Search the MCP tools the user enabled. Returns tool names and one-line descriptions. Use strata_mcp_describe before calling a tool.',
         'parameters': {'type': 'object', 'properties': {
             'query': {'type': 'string', 'description': 'Keywords such as files, browser, weather, graph'},
             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 8}},
             'required': ['query']}},
        {'name': 'strata_mcp_describe',
         'description': 'Return the JSON input schema of one enabled MCP tool.',
         'parameters': {'type': 'object', 'properties': {
             'name': {'type': 'string', 'description': 'Exact tool name from strata_mcp_search'}},
             'required': ['name']}},
        {'name': 'strata_mcp_call',
         'description': 'Call one enabled MCP tool by name. First find it with strata_mcp_search and read its schema with strata_mcp_describe; arguments must match that schema.',
         'parameters': {'type': 'object', 'properties': {
             'name': {'type': 'string'},
             'arguments': {'type': 'object', 'description': 'Arguments matching the tool schema'}},
             'required': ['name', 'arguments']}},
    ]


def _result(ok, text, started, server='codemode'):
    return {'ok': ok, 'text': text, 'chars': len(text), 'truncated': False,
            'ms': int((time.monotonic() - started) * 1000), 'server': server}


def compact_result(name, arguments, tools, hub, cancel):
    """Run one of the three compact tools against the selected MCP tools."""
    started = time.monotonic()
    if name == 'strata_mcp_search':
        query = str(arguments.get('query') or '').strip().lower()
        limit = arguments.get('limit', 8)
        if type(limit) is not int or not 1 <= limit <= 20:
            limit = 8
        rows = []
        for tool in tools:
            description = str(tool.get('description') or '')
            if query and query not in (tool['name'] + ' ' + description).lower():
                continue
            rows.append({'name': tool['name'], 'description': description[:200]})
            if len(rows) >= limit:
                break
        text = json.dumps({'tools': rows, 'count': len(rows)}, ensure_ascii=False)
        return _result(True, text, started)
    if name == 'strata_mcp_describe':
        wanted = str(arguments.get('name') or '')
        tool = next((tool for tool in tools if tool['name'] == wanted), None)
        if not tool:
            return _result(False, 'error: tool not enabled or unknown: ' + wanted, started)
        text = json.dumps({'name': wanted, 'description': tool.get('description') or '',
                           'parameters': tool.get('parameters') or {'type': 'object', 'properties': {}}},
                          ensure_ascii=False)
        return _result(True, text, started)
    wanted = str(arguments.get('name') or '')
    values = arguments.get('arguments')
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            return _result(False, 'error: arguments must be a JSON object', started)
    if not isinstance(values, dict):
        return _result(False, 'error: arguments must be an object', started)
    if not any(tool['name'] == wanted for tool in tools):
        return _result(False, 'error: tool not enabled or unknown: ' + wanted, started)
    return hub.call(wanted, values, cancel)


def chat_with_tools(manager, hub, payload, cancel):
    tools = hub.template_tools()
    selected = payload.get('strata_tools')
    if selected is not None:
        if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected):
            raise ValueError('Selezione strumenti non valida')
        tools = [t for t in tools if t['name'] in selected]
    if payload.get('strata_web') is not True:
        tools = [t for t in tools if not t['name'].endswith(('__search_web', '__read_web_page', '__weather_forecast'))]
    own = payload.get('tools') or []
    names = {t.get('function', {}).get('name') for t in own}
    tools = [t for t in tools if t['name'] not in names]
    available = {t['name'] for t in tools}
    if hasattr(manager, 'status'):
        status = manager.status()
        if status.get('publisher') == 'colibri':
            tools = []
            available = set()
    if payload.get('strata_web') is True:
        from serve.weather_intent import intent, run
        weather = next((name for name in available if name.endswith('__weather_forecast')), None)
        args = intent(payload['messages']) if weather else None
        if args:
            yield from run(hub, weather, args, manager.status()['public_model'], cancel,
                           english=str(payload.get('strata_locale', '')).startswith('en'))
            return
    if hasattr(manager, 'status'):
        status = manager.status()
        if status.get('mode') == 'safetensors' and status.get('capabilities', {}).get('tool_calling') is False:
            tools = []
            available = set()
    compact = len(tools) > COMPACT_THRESHOLD
    model_tools = ([{'type': 'function', 'function': tool} for tool in compact_tools()]
                   if compact else [{'type': 'function', 'function': tool} for tool in tools])
    if compact:
        available |= COMPACT_NAMES
    max_rounds = int(hub.settings['max_rounds']) + (2 if compact else 0)
    messages = copy.deepcopy(payload['messages'])
    usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
    budget = payload.get('max_tokens', 2048)
    for round_index in range(max_rounds + 1):
        if cancel.is_set():
            return
        request = {**payload, 'messages': messages, 'stream': bool(payload.get('stream', False)),
                   'max_tokens': budget, 'tools': own + model_tools}
        if round_index:
            request.pop('tool_choice', None)
        if round_index == max_rounds:
            request['tools'] = own
            request['messages'] = messages + [{'role': 'user', 'content': 'Return the final answer using the tool results already obtained. Explain any missing information; do not request more tools.'}]
            request['chat_template_kwargs'] = {**(request.get('chat_template_kwargs') or {}), 'enable_thinking': False}
        early_stream = request['stream']
        if early_stream:
            packets = []
            last_usage = None
            last_timings = None
            for packet in manager.chat(request, cancel):
                if packet.get('usage'):
                    last_usage = packet['usage']
                if packet.get('timings'):
                    last_timings = packet['timings']
                choices = packet.get('choices') or []
                if not choices:
                    continue
                packets.append(packet)
                delta = choices[0].get('delta') or {}
                if delta.get('content') or delta.get('reasoning_content'):
                    yield {**packet, 'choices': [{**choices[0], 'finish_reason': None}], 'usage': None}
            if not packets:
                return
            from serve.server import openai_collect
            packets[-1] = {**packets[-1], 'usage': last_usage or {'prompt_tokens': None, 'completion_tokens': None, 'total_tokens': None}}
            if last_timings:
                packets[-1]['timings'] = last_timings
            response = openai_collect(packets)
        else:
            responses = list(manager.chat(request, cancel))
            response = responses[0] if responses else None
        if response is None:
            return
        for key in usage:
            usage[key] += (response.get('usage') or {}).get(key) or 0
        budget -= (response.get('usage') or {}).get('completion_tokens') or 0
        choice = response['choices'][0]
        message = choice['message']
        calls = message.get('tool_calls') or []
        managed = calls and all(c.get('function', {}).get('name') in available for c in calls)
        base = {k: response[k] for k in ('id', 'created', 'model')}
        base['object'] = 'chat.completion.chunk'

        def chunk(delta, finish=None, **extra):
            return {**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}], **extra}
        if message.get('content') and not early_stream:
            yield chunk({'content': message['content']})
        if message.get('reasoning_content') and not early_stream:
            yield chunk({'reasoning_content': message['reasoning_content']})
        if not managed:
            if calls:
                yield chunk({'tool_calls': [{**c, 'index': i} for i, c in enumerate(calls)]})
            yield chunk({}, choice.get('finish_reason') or 'stop', usage=usage,
                        **({'timings': response['timings']} if response.get('timings') else {}))
            return
        if round_index >= max_rounds or budget <= 0:
            yield chunk({}, 'length', usage=usage, strata_mcp={'event': 'limit', 'max_rounds': max_rounds})
            return
        messages.append(message)
        for call in calls:
            if cancel.is_set():
                return
            fn = call['function']
            identity = call.get('id') or f'call_{round_index}_{len(messages)}'
            call['id'] = identity
            yield chunk({}, strata_mcp={'event': 'call', 'id': identity, 'name': fn['name'],
                                        'arguments': fn.get('arguments', '{}'), 'round': round_index + 1})
            arguments = fn.get('arguments') or {}
            for _ in range(2):
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                raise ValueError('Argomenti dello strumento non validi')
            fn['arguments'] = json.dumps(arguments, ensure_ascii=False)
            if compact and fn['name'] in COMPACT_NAMES:
                result = compact_result(fn['name'], arguments, tools, hub, cancel)
            else:
                result = hub.call(fn['name'], arguments, cancel)
            yield chunk({}, strata_mcp={'event': 'result', 'id': identity,
                                        **{k: result[k] for k in ('ok', 'text', 'chars', 'truncated', 'ms')}})
            messages.append({'role': 'tool', 'tool_call_id': identity, 'content': result['text']})
