"""Recovered local hybrid retrieval. Source bytes remain GraphMemory-owned."""
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[2] / 'Strata-main'
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


class LocalDenseProvider:
    def __init__(self, python, folder, fingerprint, *, stderr_path, asset_hashes, startup_s=25):
        self.python, self.folder = str(python), Path(folder).resolve(strict=True)
        self.fingerprint, self.hashes = fingerprint, asset_hashes
        self.stderr_path, self.startup_s = Path(stderr_path), min(float(startup_s), 60)
        self.proc = self.stderr = None
        self.responses = queue.Queue()

    def verify(self):
        if not isinstance(self.hashes, dict) or not self.hashes:
            raise ValueError('DENSE_ASSET_MANIFEST_REQUIRED')
        for name, entry in self.hashes.items():
            path = (self.folder / name).resolve(strict=True)
            if not path.is_relative_to(self.folder) or not path.is_file():
                raise ValueError('DENSE_ASSET_OUTSIDE_ROOT')
            expected = entry.get('sha256') if isinstance(entry, dict) else entry
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected:
                raise ValueError('DENSE_ASSET_IDENTITY_CHANGED: ' + name)
        required = {p.relative_to(self.folder).as_posix() for p in self.folder.rglob('*')
                    if p.is_file() and p.suffix in ('.json', '.safetensors', '.bin', '.model')}
        if not required.issubset(self.hashes):
            raise ValueError('DENSE_ASSET_MANIFEST_INCOMPLETE')

    def __enter__(self):
        from serve.hydra_execution_v10 import guarded_popen
        self.verify()
        self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.stderr = self.stderr_path.open('xb')
        env = dict(os.environ, CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='',
                   ROCR_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   OMP_NUM_THREADS='2', TOKENIZERS_PARALLELISM='false', PYTHONUTF8='1')
        try:
            self.proc = guarded_popen([self.python, str(Path(__file__).resolve()), '--dense-worker', str(self.folder)],
                cwd=PROJECT, env=env, stdin=-1, stdout=-1, stderr=self.stderr,
                text=True, encoding='utf8', creationflags=getattr(__import__('subprocess'), 'CREATE_NO_WINDOW', 0))
            self.reader = threading.Thread(target=self._read, daemon=True)
            self.reader.start()
            ready = self._receive(time.monotonic() + self.startup_s)
            if ready != {'ready': True}:
                raise ValueError('DENSE_PROVIDER_STARTUP_FAILED')
            return self
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(8 * 1024**2 + 1)
                if not line:
                    break
                if len(line) > 8 * 1024**2:
                    raise ValueError('DENSE_RESPONSE_BUDGET')
                self.responses.put(json.loads(line))
        except Exception as error:
            self.responses.put(error)
        finally:
            self.responses.put(RuntimeError('DENSE_PROVIDER_CLOSED'))

    def _receive(self, deadline):
        try:
            row = self.responses.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise TimeoutError('DENSE_PROVIDER_DEADLINE') from None
        if isinstance(row, Exception):
            raise row
        if not isinstance(row, dict) or row.get('error'):
            raise ValueError('DENSE_PROVIDER_INVALID_RESPONSE')
        return row

    def encode(self, texts, *, deadline):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError('DENSE_PROVIDER_UNAVAILABLE')
        if not isinstance(texts, list) or not 1 <= len(texts) <= 129 or any(not isinstance(t, str) or not t or len(t) > 16384 for t in texts):
            raise ValueError('DENSE_INPUT_BUDGET')
        self.proc.stdin.write(json.dumps({'texts': texts}, ensure_ascii=False) + '\n')
        self.proc.stdin.flush()
        vectors = self._receive(deadline).get('vectors')
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError('DENSE_VECTOR_COUNT')
        width = len(vectors[0]) if isinstance(vectors[0], list) else 0
        if not 1 <= width <= 4096 or any(not isinstance(v, list) or len(v) != width or any(type(x) not in (int,float) or not math.isfinite(x) for x in v) for v in vectors):
            raise ValueError('DENSE_VECTOR_INVALID')
        return vectors

    def close(self):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except __import__('subprocess').TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=5)
            for stream in (self.proc.stdin, self.proc.stdout):
                if stream:
                    stream.close()
            if getattr(self, 'reader', None):
                self.reader.join(timeout=2)
        if self.stderr is not None:
            self.stderr.close()

    def __exit__(self, *args):
        self.close()


class HybridLab:
    fusion = False
    def __init__(self, graph, provider):
        self.graph, self.provider = graph, provider

    def retrieve(self, scope, query, sources, *, deadline, enabled):
        started = time.monotonic()
        lexical = self.graph.retrieve(scope, query, allowed_sources=sources, max_nodes=16, depth=0, deadline=deadline)
        if not enabled:
            return self.result(lexical[:2], 'lexical', False, 'hybrid_disabled', started, len(lexical))
        # Obtain IDs only; GraphMemory revalidates allowlists, scope, age and source bytes.
        from contextlib import closing
        with closing(self.graph._connect()) as db:
            ids = [r[0] for r in db.execute('SELECT id FROM nodes WHERE scope=? AND current=1 ORDER BY id LIMIT 128', (scope,))]
        candidates = {}
        for offset in range(0, len(ids), 16):
            for row in self.graph.retrieve(scope, query, allowed_sources=sources, max_nodes=16, depth=0,
                    ranked_node_ids=ids[offset:offset+16], deadline=deadline):
                candidates[row['id']] = row
        for row in lexical:
            candidates[row['id']] = row
        rows = list(candidates.values())[:128]
        if not rows:
            return self.result([], 'hybrid_cpu', False, 'no_verified_sources', started, 0)
        vectors = self.provider.encode([query] + [r['content'] for r in rows], deadline=deadline)
        def cosine(vector):
            a, b = vectors[0], vector
            norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
            return sum(x*y for x,y in zip(a,b)) / norm if norm else 0
        dense = sorted(range(len(rows)), key=lambda i: (-cosine(vectors[i+1]), rows[i]['id']))
        ranks = {rows[i]['id']: rank for rank,i in enumerate(dense)}
        lexical_ranks = {r['id']: rank for rank,r in enumerate(lexical)}
        def score(row):
            identity = row['id']
            return 1/(60+ranks[identity]) + (1/(60+lexical_ranks[identity]) if self.fusion and identity in lexical_ranks else 0)
        rows.sort(key=lambda row: (-score(row), row['id']))
        selected = self.graph.retrieve(scope, query, allowed_sources=sources, max_nodes=2, depth=0,
            ranked_node_ids=[r['id'] for r in rows[:2]], deadline=deadline)
        return self.result(selected, 'hybrid_cpu_rrf' if self.fusion else 'dense_cpu_verified', False, 'verified_local_dense_ranking', started, len(rows))

    @staticmethod
    def result(nodes, strategy, fallback, reason, started, candidates):
        return SimpleNamespace(nodes=nodes, strategy=strategy, fallback=fallback, reason=reason,
            coverage=dict(verified_candidates=candidates, returned=len(nodes)),
            metrics=dict(elapsed_ms=(time.monotonic()-started)*1000, gpu=False,
                         reconstruction='20261022; historical H1/H1v2 quality parity not certified'))


def worker(folder):
    from serve.hydra_execution_v10 import require_child_admission
    require_child_admission()
    # Reuse the installed Transformers runtime and the recovered mean-pooling model.
    import torch
    from transformers import AutoModel, AutoTokenizer
    folder = Path(folder)
    modules=json.loads((folder/'modules.json').read_text())
    if [m.get('type') for m in modules] != ['sentence_transformers.models.Transformer','sentence_transformers.models.Pooling']:
        raise ValueError('DENSE_POOLING_ARCHITECTURE_UNSUPPORTED')
    pooling_path=(folder/modules[1]['path']).resolve(strict=True)
    if not pooling_path.is_relative_to(folder.resolve()):raise ValueError('DENSE_POOLING_OUTSIDE_ROOT')
    pooling=json.loads((pooling_path/'config.json').read_text())
    if pooling.get('pooling_mode_mean_tokens') is not True or any(v for k,v in pooling.items() if k.startswith('pooling_mode_') and k!='pooling_mode_mean_tokens'):
        raise ValueError('DENSE_POOLING_MODE_UNSUPPORTED')
    max_length=json.loads((folder/'sentence_bert_config.json').read_text())['max_seq_length']
    if type(max_length) is not int or not 1<=max_length<=512:raise ValueError('DENSE_TOKEN_BUDGET')
    torch.set_num_threads(2)
    tokenizer=AutoTokenizer.from_pretrained(folder,local_files_only=True,trust_remote_code=False)
    model=AutoModel.from_pretrained(folder,local_files_only=True,trust_remote_code=False).to('cpu').eval()
    print(json.dumps({'ready': True}), flush=True)
    while True:
        line = sys.stdin.readline(4*1024**2+1)
        if not line:
            return
        if len(line)>4*1024**2:
            raise ValueError('DENSE_INPUT_BUDGET')
        row=json.loads(line);texts=row.get('texts')
        if set(row)!={'texts'} or not isinstance(texts,list) or not 1<=len(texts)<=129 or any(not isinstance(t,str) or not t or len(t)>16384 for t in texts):
            raise ValueError('DENSE_INPUT_BUDGET')
        vectors=[]
        with torch.inference_mode():
            for offset in range(0,len(texts),4):
                inputs=tokenizer(texts[offset:offset+4],padding=True,truncation=True,max_length=max_length,return_tensors='pt')
                hidden=model(**inputs).last_hidden_state
                mask=inputs['attention_mask'].unsqueeze(-1).to(hidden.dtype)
                pooled=(hidden*mask).sum(dim=1)/mask.sum(dim=1).clamp(min=1e-9)
                vectors.extend(torch.nn.functional.normalize(pooled,p=2,dim=1).tolist())
        print(json.dumps({'vectors':vectors},allow_nan=False),flush=True)


if __name__ == '__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--dense-worker':
        raise SystemExit('explicit --dense-worker and local model required')
    worker(sys.argv[2])
