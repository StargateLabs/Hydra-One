"""Stable dashboard model alias; explicit model identifiers never silently fall back."""
class ModelNotFound(ValueError):
    """An explicit model identifier is not served by this gateway."""


def local_selection(svc):
    optional = svc.optional_backends.status()
    if optional.get('status') == 'ready' and optional.get('public_model'):
        context = optional.get('context_per_slot') or optional.get('context') or 4096
        model = optional['public_model']
        tool_calling = (optional.get('capabilities') or {}).get('tool_calling', 'model_dependent')
        output_limit = 4096
    else:
        context = getattr(svc.engine, 'max_context', None) or getattr(svc, 'max_context', None) or 4096
        model = svc.model
        tool_calling = 'model_dependent'
        output_limit = 16384
    context = max(256, int(context))
    result = {'model': model, 'context': context, 'output': min(output_limit, max(64, context // 4)), 'tool_calling': tool_calling}
    if optional.get('status') == 'ready' and optional.get('engine_addon') == 'hydra-one':
        result.update(engine_addon='hydra-one', backend=optional.get('backend'))
    elif optional.get('status') != 'ready' and getattr(svc,'hydra_native_state',{}).get('enabled'):
        result.update(engine_addon='hydra-one',backend='HYDRA ONE · Strata native')
    return result


def resolve_request(svc, req):
    selection = local_selection(svc)
    asked = req.get('model')
    if asked in ('strata', selection['model']) and selection['tool_calling'] is False and req.get('tools'):
        raise ValueError('Il runtime del modello selezionato non supporta chiamate strumenti; usa conversazione senza strumenti')
    if asked == 'strata':
        req = dict(req, model=selection['model'])
        for key in ('max_tokens', 'max_completion_tokens'):
            if key in req and int(req[key] or 0) > selection['output']:
                req[key] = selection['output']
        return req
    if asked and asked not in svc.model_names() and asked != selection['model']:
        raise ModelNotFound('Il modello richiesto non e disponibile: '+str(asked))
    return req
