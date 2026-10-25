from urllib.parse import urlsplit,parse_qs
def get(handler,service,path):
    if path!='/inference-backends/model-engine':return False
    if not handler._authorized():return True
    try:
        model=parse_qs(urlsplit(handler.path).query).get('path',[''])[0]
        if not model or len(model)>4096:raise ValueError('Indica il percorso del modello')
        from serve.model_engine_requirements import requirement
        handler._json(200,requirement(service.update_center.root,model))
    except (OSError,ValueError,TypeError) as error:handler._json(400,{'error':{'message':str(error)}})
    return True
