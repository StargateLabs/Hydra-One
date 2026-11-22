"""Original Open WebUI embedding adapter; core verified document worker stays unchanged."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import open_webui_worker as original
from open_webui_runtime import embedding_models

def run(payload):
    if payload.get('action')!='semantic':raise ValueError('Unsupported semantic action')
    if payload.get('embedding_model') not in {row['path'] for row in embedding_models(original.ROOT)}:raise ValueError('Local embedding model is unavailable')
    original.run({'action':'device'})
    from sentence_transformers import SentenceTransformer,util
    from open_webui.retrieval.utils import get_embedding_function
    model=SentenceTransformer(payload['embedding_model'],device='cpu',local_files_only=True,trust_remote_code=False,model_kwargs={'use_safetensors':True})
    embed=get_embedding_function('',payload['embedding_model'],model,'','',8)
    chunks=payload['chunks']
    vectors=asyncio.run(embed([payload['query']]+[row['text'] for row in chunks]))
    matches=util.semantic_search(__import__('torch').tensor(vectors[:1]),__import__('torch').tensor(vectors[1:]),top_k=min(4,len(chunks)))[0]
    return {'processor':'Open WebUI','version':'0.12.0','method':'Open WebUI local embeddings · cosine retrieval','embedding_model':Path(payload['embedding_model']).name,'matches':[{'text':chunks[row['corpus_id']]['text'],'page':chunks[row['corpus_id']]['page'],'chunk':row['corpus_id'],'score':row['score']} for row in matches]}

if __name__=='__main__':
    try:
        payload=json.loads(sys.stdin.buffer.read(2*1024*1024+1));result=run(payload)
        print('STARGATE_RESULT:'+json.dumps(result,ensure_ascii=True),flush=True)
    except Exception as error:
        print('STARGATE_RESULT:'+json.dumps({'error':str(error)},ensure_ascii=True),flush=True);raise SystemExit(1)
