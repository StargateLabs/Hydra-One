"""Explicit bounded JSON Schema subset, not a complete draft implementation."""
import math

KEYS={'type','properties','required','additionalProperties','items','minItems','maxItems',
      'minLength','maxLength','minimum','maximum','enum','description','title'}
TYPES={'object','array','string','integer','number','boolean','null'}


def validate_schema(schema, *, _depth=0, _nodes=None):
    nodes=[0] if _nodes is None else _nodes;nodes[0]+=1
    if _depth>16 or nodes[0]>256:raise ValueError('Schema complexity bound exceeded')
    if not isinstance(schema,dict) or set(schema)-KEYS or not isinstance(schema.get('type'),str) or schema.get('type') not in TYPES:
        raise ValueError('Unsupported or incomplete schema')
    typ=schema['type']
    for name in ('title','description'):
        if name in schema and not isinstance(schema[name],str):raise ValueError('Schema annotation must be string')
    if 'enum' in schema and (not isinstance(schema['enum'],list) or not schema['enum'] or len(schema['enum'])>256):
        raise ValueError('Bounded nonempty enum required')
    if any(k in schema for k in ('properties','required','additionalProperties')) and typ!='object':
        raise ValueError('Object keyword on non-object schema')
    if 'properties' in schema:
        if not isinstance(schema['properties'],dict) or any(not isinstance(k,str) for k in schema['properties']):raise ValueError('Invalid properties')
        for child in schema['properties'].values():validate_schema(child,_depth=_depth+1,_nodes=nodes)
    required=schema.get('required',[])
    if not isinstance(required,list) or any(not isinstance(k,str) or k not in schema.get('properties',{}) for k in required) or len(set(required))!=len(required):
        raise ValueError('Required entries must be declared properties')
    if 'additionalProperties' in schema and type(schema['additionalProperties']) is not bool:raise ValueError('Only boolean additionalProperties supported')
    if 'items' in schema:
        if typ!='array':raise ValueError('Items on non-array schema')
        validate_schema(schema['items'],_depth=_depth+1,_nodes=nodes)
    if typ=='array' and 'items' not in schema:raise ValueError('Explicit array items schema required')
    for low,high,expected in [('minItems','maxItems','array'),('minLength','maxLength','string')]:
        for key in (low,high):
            if key in schema and (typ!=expected or type(schema[key]) is not int or schema[key]<0):raise ValueError('Invalid bound '+key)
        if low in schema and high in schema and schema[low]>schema[high]:raise ValueError('Inverted schema bounds')
    for key in ('minimum','maximum'):
        if key in schema and (typ not in ('integer','number') or type(schema[key]) not in (int,float) or not math.isfinite(schema[key])):raise ValueError('Invalid numeric bound')
    if 'minimum' in schema and 'maximum' in schema and schema['minimum']>schema['maximum']:raise ValueError('Inverted numeric bounds')


def validate_value(value,schema, *, _depth=0):
    if _depth==0:validate_schema(schema)
    if _depth>16:raise ValueError('Value depth limit exceeded')
    typ=schema['type']
    valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),
           'integer':type(value) is int,'number':type(value) in (int,float),'boolean':type(value) is bool,'null':value is None}[typ]
    if not valid:raise ValueError('Output does not match schema type')
    if type(value) in (int,float) and not math.isfinite(value):raise ValueError('Nonfinite number')
    if 'enum' in schema and not any(type(value) is type(v) and value==v for v in schema['enum']):raise ValueError('Output outside enum')
    if typ=='object':
        properties=schema.get('properties',{})
        if any(k not in value for k in schema.get('required',[])):raise ValueError('Missing required property')
        if schema.get('additionalProperties') is False and set(value)-set(properties):raise ValueError('Unexpected property')
        for key,item in value.items():
            if key in properties:validate_value(item,properties[key],_depth=_depth+1)
    if typ=='array':
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',len(value)):raise ValueError('Array length outside bounds')
        for item in value:validate_value(item,schema['items'],_depth=_depth+1)
    if typ=='string' and (len(value)<schema.get('minLength',0) or len(value)>schema.get('maxLength',len(value))):raise ValueError('String length outside bounds')
    if typ in ('number','integer') and (value<schema.get('minimum',value) or value>schema.get('maximum',value)):raise ValueError('Number outside bounds')
