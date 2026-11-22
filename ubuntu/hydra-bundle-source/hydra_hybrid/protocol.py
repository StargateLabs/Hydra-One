"""Single-choice chat contract; no execution of tools or JSON-schema engine."""
import json
import re
from .schema import validate_schema, validate_value


def cache_request(request, policy):
    """Copy only; native backend owns reuse and may ignore unsupported options."""
    result = dict(request)
    if 'cache_prompt' in result and type(result['cache_prompt']) is not bool:
        raise ValueError('Boolean cache_prompt required')
    if policy == 'off':
        result['cache_prompt'] = False
    elif policy == 'native':
        result.setdefault('cache_prompt', True)
    elif policy != 'inherit':
        raise ValueError('Invalid prompt cache policy')
    return result


def strict_json(text):
    def invalid(value):
        raise ValueError('Non-finite JSON constant')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    return json.loads(text, parse_constant=invalid, object_pairs_hook=pairs)


def validate_request(request):
    if type(request.get('n', 1)) is not int or request.get('n', 1) != 1:
        raise ValueError('Only single-choice n=1 supported')
    if 'max_completion_tokens' in request:
        raise ValueError('Use the bounded max_tokens contract')
    fmt = request.get('response_format', {'type':'text'})
    if not isinstance(fmt, dict) or fmt.get('type') not in ('text', 'json_object', 'json_schema'):
        raise ValueError('Unsupported output contract')
    if fmt.get('type')=='json_schema':
        descriptor=fmt.get('json_schema')
        if not isinstance(descriptor,dict) or descriptor.get('strict') is not True or not isinstance(descriptor.get('name'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',descriptor['name']):
            raise ValueError('Explicit named strict JSON schema required')
        validate_schema(descriptor.get('schema'))
    tools = request.get('tools', [])
    if not isinstance(tools, list):
        raise ValueError('Tools array required')
    names = set()
    for tool in tools:
        function = tool.get('function') if isinstance(tool, dict) else None
        if not isinstance(function, dict) or tool.get('type') != 'function':
            raise ValueError('Function tool required')
        name = function.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name) or name in names:
            raise ValueError('Unique bounded function names required')
        if 'parameters' in function and not isinstance(function['parameters'], dict):
            raise ValueError('Tool parameters must be a schema object; semantic schema validation unavailable')
        if function.get('parameters'):
            validate_schema(function['parameters'])
        names.add(name)
    choice = request.get('tool_choice', 'auto')
    if isinstance(choice, str):
        if choice not in ('none', 'auto', 'required'):
            raise ValueError('Unsupported tool_choice')
        if choice == 'required' and not names:
            raise ValueError('Required tool choice needs declared tools')
    elif isinstance(choice, dict):
        function = choice.get('function')
        if choice.get('type') != 'function' or not isinstance(function, dict) or not isinstance(function.get('name'), str) or function.get('name') not in names:
            raise ValueError('Named tool choice must refer to a declared function')
    else:
        raise ValueError('Invalid tool_choice')


class StreamContract:
    """Validate only observable payload semantics; never performs tool calls."""
    def __init__(self, request):
        validate_request(request)
        self.json_object = request.get('response_format', {}).get('type') == 'json_object'
        self.schema = request.get('response_format', {}).get('json_schema',{}).get('schema') if request.get('response_format',{}).get('type')=='json_schema' else None
        self.content = []
        self.calls = {}
        self.names = {t['function']['name'] for t in request.get('tools', [])}
        self.choice = request.get('tool_choice', 'auto')
        self.tool_schemas={t['function']['name']:t['function'].get('parameters') for t in request.get('tools',[])}

    def observe(self, choice):
        if not isinstance(choice, dict) or type(choice.get('index', 0)) is not int or choice.get('index', 0) != 0:
            raise ValueError('Only choice index 0 supported')
        delta = choice.get('delta', {})
        if not isinstance(delta, dict):
            raise ValueError('Invalid delta')
        if delta.get('content') is not None:
            if not isinstance(delta['content'], str):
                raise ValueError('Invalid content')
            if self.json_object or self.schema is not None:
                self.content.append(delta['content'])
        if delta.get('tool_calls') is None:
            return
        if not isinstance(delta['tool_calls'], list):
            raise ValueError('Tool deltas array required')
        for fragment in delta['tool_calls']:
            if not isinstance(fragment, dict):
                raise ValueError('Tool delta object required')
            index = fragment.get('index')
            if type(index) is not int or index < 0:
                raise ValueError('Nonnegative tool index required')
            call = self.calls.setdefault(index, dict(id=None, name='', arguments=''))
            if 'id' in fragment:
                ident = fragment['id']
                if not isinstance(ident, str) or not ident or (call['id'] is not None and call['id'] != ident):
                    raise ValueError('Tool identity changed')
                call['id'] = ident
            if 'type' in fragment and fragment['type'] != 'function':
                raise ValueError('Unsupported tool type')
            function = fragment.get('function', {})
            if not isinstance(function, dict):
                raise ValueError('Invalid function delta')
            for name in ('name','arguments'):
                if name in function:
                    if not isinstance(function[name], str):
                        raise ValueError('Function fields must be strings')
                    call[name] += function[name]

    def finish(self):
        if self.json_object and not isinstance(strict_json(''.join(self.content)), dict):
            raise ValueError('Expected JSON object output')
        if self.schema is not None:
            validate_value(strict_json(''.join(self.content)),self.schema)
        seen = set()
        if self.choice == 'none' and self.calls:
            raise ValueError('Tool calls forbidden by tool_choice')
        if (self.choice == 'required' or isinstance(self.choice, dict)) and not self.calls:
            raise ValueError('Requested tool call missing')
        for call in self.calls.values():
            if call['id'] is None or call['id'] in seen or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', call['name']):
                raise ValueError('Incomplete/duplicate tool identity')
            seen.add(call['id'])
            if self.names and call['name'] not in self.names:
                raise ValueError('Undeclared function name')
            if isinstance(self.choice, dict) and call['name'] != self.choice['function']['name']:
                raise ValueError('Function differs from requested tool choice')
            arguments=strict_json(call['arguments'])
            if not isinstance(arguments, dict):
                raise ValueError('Function arguments must form a JSON object')
            if self.tool_schemas.get(call['name']):
                validate_value(arguments,self.tool_schemas[call['name']])
