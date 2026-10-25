"""Reuse HYDRA's graph compiler with the owned GGUF runtime's exact frontend."""
import http.client
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace


class RuntimeTemplate:
    def __init__(self,post,options):self.post=post;self.options=options

    def render(self,messages,tools=None,**kwargs):
        # Keep this identical to LocalOpenAIBackend.chat's wire normalization.
        instructions=[m.get('content') for m in messages if m.get('role') in ('system','developer')]
        normalized=([dict(role='system',content='\n\n'.join(instructions))] if instructions else [])+[
            m for m in messages if m.get('role') not in ('system','developer')]
        body=dict(self.options,messages=normalized,model='optional-model')
        if tools:body['tools']=tools
        prompt=self.post('/apply-template',body)['prompt']
        if not isinstance(prompt,str):raise ValueError('Runtime template is not plain text')
        return prompt


class RuntimeTokenizer:
    """Read the model's special inventory only for a verified graph candidate."""
    def __init__(self,bridge):
        self.bridge=bridge;self._special_tokens=None

    @property
    def special_tokens(self):
        if self._special_tokens is None:
            from serve.hydra_graph_memory import _deadline
            _deadline(self.bridge.deadline)
            # Existing header reader only; tensor weights are never read here.
            from tools.gguf_reader import GGUFFile
            metadata=GGUFFile(Path(self.bridge.payload['model_path'])).metadata
            tokens=metadata.get('tokenizer.ggml.tokens') or []
            types=metadata.get('tokenizer.ggml.token_type') or []
            specials={token:i for i,(token,kind) in enumerate(zip(tokens,types)) if kind in (3,4)}
            if not specials:raise ValueError('Special token inventory unavailable')
            _deadline(self.bridge.deadline)
            self._special_tokens=specials
        return self._special_tokens

    def encode(self,prompt,parse_special=True):
        ids=self.bridge.post('/tokenize',dict(content=prompt,add_special=False,parse_special=parse_special))['tokens']
        if not isinstance(ids,list) or any(type(v) is not int or v<0 for v in ids):
            raise ValueError('Invalid runtime tokens')
        return ids


class OptionalGraph:
    def __init__(self,owner,client,payload):
        self.owner=owner;self.client=client;self.payload=payload
        self.service=None;self.lock=threading.Lock();self.last_error=None;self.bypass='awaiting_request'
        self.deadline=0

    def post(self,path,body):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Graph runtime deadline')
        connection=http.client.HTTPConnection(self.client.host,self.client.port,timeout=remaining)
        try:
            connection.request('POST',path,json.dumps(body,ensure_ascii=False).encode('utf-8'),
                               {'Content-Type':'application/json'})
            response=connection.getresponse()
            raw=response.read((16<<20)+1)
            if response.status!=200 or len(raw)>16<<20:raise ValueError('Runtime preparation unavailable')
            return json.loads(raw)
        finally:connection.close()

    def initialize(self):
        # Cheap policy decisions must not parse the model or contact its runtime.
        # Tokenization itself still belongs exclusively to the owned runtime.
        context=self.context_limit()
        self.service=SimpleNamespace(cfg={},hydra_native_state={'enabled':True},
            engine=SimpleNamespace(max_context=context),
            tok=RuntimeTokenizer(self))

    def context_limit(self):
        requested=self.payload.get('context',4096)
        observed=(getattr(self.owner,'state',{}) or {}).get('context',requested)
        if type(observed) is not int or observed<=0:raise ValueError('Context unavailable')
        return min(requested,observed)//max(1,(self.payload.get('runtime') or {}).get('slots',1))

    def prepare(self,messages,options,max_tokens):
        original=messages
        try:
            self.last_error=None
            config=getattr(self.owner,'graph_config',lambda:{})()
            if not isinstance(config,dict) or not config.get('graph_enabled') or not config.get('context_compiler_enabled'):
                if self.service is not None:self.service.cfg={}
                self.bypass='disabled'
                return original
            cancel=options.get('cancel')
            if self.payload.get('mode')!='gguf' or options.get('response_format') or options.get('tools') or (cancel is not None and cancel.is_set()):
                self.bypass='protected_request'
                return original
            if not self.lock.acquire(False):
                self.bypass='preparation_busy'
                return original
            try:
                from serve.hydra_graph import prepare,validate_options
                config=validate_options(config)
                self.deadline=time.monotonic()+config['timeout_ms']/1000
                if self.service is None:self.initialize()
                self.service.engine.max_context=self.context_limit()
                self.service.cfg={'hydra_graph_inference':config}
                template_options={key:value for key,value in options.items() if key in (
                    'chat_template_kwargs','enable_thinking','reasoning_effort')}
                self.service.template=RuntimeTemplate(self.post,template_options)
                result=prepare(self.service,messages,None,{},max_tokens)
                self.bypass=None
                return result
            finally:self.lock.release()
        except Exception as exc:
            self.last_error=type(exc).__name__[:64]
            return original

    def snapshot(self):
        if self.last_error:
            return dict(enabled=False,last=dict(strategy='standard',fallback=True,
                reason='runtime_preparation_unavailable',error_type=self.last_error))
        if self.bypass is not None:
            return dict(enabled=self.bypass!='disabled',last=dict(strategy='standard',reason=self.bypass,
                fallback=self.bypass in ('controller_admission','preparation_busy')))
        if self.service is None:return dict(enabled=False)
        from serve.hydra_graph import snapshot
        return snapshot(self.service)
