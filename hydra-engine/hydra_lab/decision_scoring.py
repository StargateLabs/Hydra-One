"""Recovered exact-prefix CPU scoring through the separately attested helper."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


class NativeCPUBackend:
    def __init__(self, helper, runtime, model, runtime_manifest, data, *, model_sha256,
                 prefix_cache=False, checkpoint_limit_bytes=16*1024**2, checkpoint_tier='ram'):
        self.helper,self.runtime,self.model,self.data=map(Path,(helper,runtime,model,data))
        self.model_hash=model_sha256
        if prefix_cache or checkpoint_tier!='ram':
            raise ValueError('RECOVERED_SCORER_CHECKPOINT_NOT_CERTIFIED')
        manifest=Path(__file__).resolve().parents[1]/'engine_completion_v22/native-score-recovery-manifest.json'
        receipt=json.loads(manifest.read_text(encoding='utf8'))
        if self.helper.resolve()!=Path(receipt['executable']).resolve() or sha(self.helper)!=receipt['sha256']:
            raise ValueError('RECOVERED_SCORER_IDENTITY_CHANGED')
        if sha(self.model)!=model_sha256:
            raise ValueError('SCORER_MODEL_IDENTITY_CHANGED')
        files=runtime_manifest.get('files')
        if not isinstance(files,dict) or not files:
            raise ValueError('SCORER_RUNTIME_MANIFEST_REQUIRED')
        for name,row in files.items():
            if Path(name).name!=name or sha(self.runtime/name)!=row['sha256']:
                raise ValueError('SCORER_RUNTIME_IDENTITY_CHANGED')
        for name,expected in receipt['runtime_sha256'].items():
            if Path(name).name!=name or sha(self.runtime/name)!=expected:
                raise ValueError('SCORER_RUNTIME_ABI_NOT_ATTESTED')
        self.last=None

    def score(self,request):
        from serve.hydra_execution_v10 import guarded_popen
        if request.get('backend')!='llama.cpp-cpu-capi' or request.get('mode')!='continuation_logprobs' or request.get('repeat')!=1:
            raise ValueError('SCORER_REQUEST_CONTRACT')
        alternatives=request.get('alternatives')
        if not isinstance(alternatives,list) or not 1<=len(alternatives)<=4:
            raise ValueError('SCORER_ALTERNATIVE_BUDGET')
        seen=set()
        for row in alternatives:
            if not isinstance(row,dict) or set(row)!={'id','text'} or not isinstance(row['id'],str) or not 1<=len(row['id'])<=128 or row['id'] in seen or not isinstance(row['text'],str) or not 1<=len(row['text'])<=1024:
                raise ValueError('SCORER_ALTERNATIVE_IDENTITY')
            seen.add(row['id'])
        prefix=request.get('prefix_text')
        if prefix is None:
            document,question=request.get('document'),request.get('question')
            if not isinstance(document,str) or not isinstance(question,str):raise ValueError('SCORER_TEXT_REQUIRED')
            prefix=document+'\n'+question+'\n'
        if not isinstance(prefix,str) or not 1<=len(prefix)<=4096:
            raise ValueError('SCORER_PREFIX_BUDGET')
        normalize=request.get('normalize','sum')
        if normalize not in ('sum','mean'):raise ValueError('SCORER_NORMALIZATION')
        remaining=min(40,request.get('deadline',time.monotonic()+40)-time.monotonic())
        if remaining<=0:raise TimeoutError('SCORER_DEADLINE')
        self.data.mkdir(parents=True,exist_ok=True)
        path=self.data/('scorer-'+uuid.uuid4().hex+'.stderr')
        env=dict(os.environ,PATH=str(self.runtime)+os.pathsep+os.environ.get('PATH',''),
                 CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',ROCR_VISIBLE_DEVICES='',OMP_NUM_THREADS='2')
        env.pop('GGML_BACKEND_PATH',None)
        body=json.dumps(dict(prefix_text=prefix,alternatives=alternatives,normalize=normalize),ensure_ascii=False)
        if len(body.encode('utf8'))>32768:raise ValueError('SCORER_REQUEST_BYTES')
        with path.open('xb') as log:
            child=guarded_popen([str(self.helper),str(self.model)],cwd=self.runtime,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf8',
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                output,_=child.communicate(body+'\n',timeout=remaining)
            except BaseException:
                child.kill();child.communicate();raise
            finally:
                self.last=dict(pid=child.pid,exit_code=child.returncode,cleanup=child.poll() is not None,stderr=str(path))
        if child.returncode:raise RuntimeError('NATIVE_SCORING_FAILED: '+path.read_text(errors='replace')[-1200:])
        if len(output)>2*1024**2:raise ValueError('SCORER_OUTPUT_BUDGET')
        result=json.loads(output)
        if [r.get('id') for r in result.get('alternatives',[])] != [r['id'] for r in alternatives]:
            raise ValueError('SCORER_RESPONSE_IDENTITY')
        result['provenance'].update(model_sha256=self.model_hash,helper_sha256=sha(self.helper),
            template=request.get('template'),reconstruction='20261022; historical quality/parity not certified')
        return result


def score_alternatives(request,backend):
    return backend.score(request)
