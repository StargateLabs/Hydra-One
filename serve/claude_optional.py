"""Strict Anthropic adapter for the existing optional OpenAI backend API."""
import json
import uuid


def to_openai(req):
    messages = []
    system = req.get('system')
    if system:
        if isinstance(system, list):
            if any(b.get('type') != 'text' for b in system): raise ValueError('Unsupported system content')
            system = '\n'.join(b['text'] for b in system)
        messages.append({'role': 'system', 'content': system})
    for message in req.get('messages', []):
        content = message.get('content', '')
        if isinstance(content, str):
            messages.append({'role': message['role'], 'content': content})
            continue
        text, calls = [], []
        for block in content:
            kind = block.get('type')
            if kind == 'text': text.append(block['text'])
            elif kind == 'tool_use':
                calls.append({'id': block['id'], 'type': 'function', 'function': {'name': block['name'], 'arguments': json.dumps(block['input'])}})
            elif kind == 'tool_result':
                result = block.get('content', '')
                if isinstance(result, list):
                    if any(b.get('type') != 'text' for b in result): raise ValueError('Unsupported tool result content')
                    result = '\n'.join(b['text'] for b in result)
                messages.append({'role': 'tool', 'tool_call_id': block['tool_use_id'], 'content': result})
            else: raise ValueError('Unsupported Anthropic content block: '+str(kind))
        if text or calls:
            row = {'role': message['role'], 'content': '\n'.join(text)}
            if calls: row['tool_calls'] = calls
            messages.append(row)
    payload = {'model': req['model'], 'messages': messages, 'stream': False}
    for key in ('temperature', 'top_p', 'max_tokens'): 
        if key in req: payload[key] = req[key]
    if isinstance(req.get('chat_template_kwargs'),dict):payload['chat_template_kwargs']=dict(req['chat_template_kwargs'])
    if req.get('thinking',{}).get('type')=='disabled':payload['chat_template_kwargs']={**payload.get('chat_template_kwargs',{}),'enable_thinking':False}
    if 'stop_sequences' in req: payload['stop'] = req['stop_sequences']
    if req.get('tools'):
        payload['tools'] = [{'type': 'function', 'function': {'name': t['name'], 'description': t.get('description', ''), 'parameters': t['input_schema']}} for t in req['tools']]
    choice = req.get('tool_choice')
    if choice:
        mode = choice.get('type')
        if mode == 'tool': payload['tool_choice'] = {'type': 'function', 'function': {'name': choice['name']}}
        elif mode in ('auto', 'none', 'any'): payload['tool_choice'] = 'required' if mode == 'any' else mode
        else: raise ValueError('Unsupported tool choice')
    return payload


def from_openai(response, model):
    usage = response.get('usage') or {}
    if not all(type(usage.get(key)) is int and usage[key] >= 0 for key in ('prompt_tokens', 'completion_tokens')):
        raise ValueError('Il backend non fornisce conteggi token reali')
    choice = response['choices'][0]
    msg = choice['message']
    content = []
    if msg.get('content'): content.append({'type': 'text', 'text': msg['content']})
    for call in msg.get('tool_calls') or []:
        content.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
    stop = {'stop': 'end_turn', 'length': 'max_tokens', 'tool_calls': 'tool_use'}.get(choice.get('finish_reason'))
    if not stop: raise ValueError('Unsupported backend finish reason')
    return {'id': 'msg_'+uuid.uuid4().hex, 'type': 'message', 'role': 'assistant', 'model': model,
            'content': content, 'stop_reason': stop, 'stop_sequence': None,
            'usage': {'input_tokens': usage['prompt_tokens'], 'output_tokens': usage['completion_tokens']}}


def stream_events(message):
    start = {**message, 'content': [], 'stop_reason': None, 'usage': {**message['usage'], 'output_tokens': 0}}
    yield 'message_start', {'type': 'message_start', 'message': start}
    for index, block in enumerate(message['content']):
        initial = {**block, 'text': ''} if block['type'] == 'text' else {**block, 'input': {}}
        yield 'content_block_start', {'type': 'content_block_start', 'index': index, 'content_block': initial}
        delta = {'type': 'text_delta', 'text': block['text']} if block['type'] == 'text' else {'type': 'input_json_delta', 'partial_json': json.dumps(block['input'])}
        yield 'content_block_delta', {'type': 'content_block_delta', 'index': index, 'delta': delta}
        yield 'content_block_stop', {'type': 'content_block_stop', 'index': index}
    yield 'message_delta', {'type': 'message_delta', 'delta': {'stop_reason': message['stop_reason'], 'stop_sequence': None}, 'usage': {'output_tokens': message['usage']['output_tokens']}}
    yield 'message_stop', {'type': 'message_stop'}
