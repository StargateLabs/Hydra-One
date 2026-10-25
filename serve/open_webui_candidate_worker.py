"""Original Open WebUI document/context functions in an owned offline CPU child."""
import json, os, sys, secrets
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
data=Path(os.environ['STRATA_OPEN_WEBUI_DATA'])
data.mkdir(parents=True,exist_ok=True)
import importlib.util
package=Path(importlib.util.find_spec('open_webui').origin).parent
os.environ.update(FRONTEND_BUILD_DIR=str(package/'frontend'),STATIC_DIR=str(data/'static'),DATA_DIR=str(data),DATABASE_URL='sqlite:///'+str(data/'webui.db'),
    WEBUI_AUTH='false',WEBUI_SECRET_KEY=secrets.token_hex(32),OFFLINE_MODE='true',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
    ENABLE_VERSION_UPDATE_CHECK='false',ENABLE_PERSISTENT_CONFIG='false',
    CORS_ALLOW_ORIGIN='http://127.0.0.1',DO_NOT_TRACK='true',ANONYMIZED_TELEMETRY='false',USER_AGENT='StargateLab-Internal',
    CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')

def run_basic(payload):
    import importlib.metadata
    version=importlib.metadata.version('open-webui')
    if version!=os.environ['STRATA_OPEN_WEBUI_VERSION']:raise ValueError('Open WebUI version changed; validate this integration again')
    action=payload['action']
    if action=='verify':
        jobs=payload.get('jobs')
        if not isinstance(jobs,dict) or len(jobs)>8:raise ValueError('Invalid verification batch')
        return {key:run_basic(value) for key,value in jobs.items()}
    if action=='device':
        import torch
        if torch.version.cuda is not None or torch.version.hip is not None:raise ValueError('Open WebUI internal functions require their isolated CPU runtime')
        return {'device':'cpu','torch':torch.__version__}
    if action=='context':
        from open_webui.utils.context_compaction import _find_compaction_boundary,_estimate_messages_tokens
        messages=payload['messages']
        return {'processor':'Open WebUI','version':version,'estimated_tokens':_estimate_messages_tokens(messages),
                'boundary':_find_compaction_boundary(messages,retention_percentage=40)}
    from open_webui.retrieval.loaders.main import Loader
    if action=='extract':
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        loader=Loader({'rag.content_extraction_engine':'','rag.pdf_extract_images':False,'rag.pdf_loader_mode':'page','rag.file.max_size':8})
        if payload['mime']=='application/pdf':
            from pypdf import PdfReader
            pdf=PdfReader(payload['path'])
            if pdf.is_encrypted or len(pdf.pages)>100:raise ValueError('PDF must be unencrypted and at most 100 pages')
        docs=loader.load(payload['name'],payload['mime'],payload['path'])
        if len(docs)>100:raise ValueError('Document exceeds 100 pages')
        if sum(len(d.page_content) for d in docs)>1000000:raise ValueError('Extracted document exceeds one million characters')
        chunks=RecursiveCharacterTextSplitter(chunk_size=1800,chunk_overlap=180).split_documents(docs)
        if not chunks or not any(d.page_content.strip() for d in chunks):raise ValueError('No readable text; image-only scans require OCR')
        return {'processor':'Open WebUI','version':version,'pages':len(docs) if payload['mime']=='application/pdf' else None,
                'chunks':[{'text':d.page_content,'page':d.metadata['page']+1 if isinstance(d.metadata.get('page'),int) else None} for d in chunks]}
    if action=='search':
        from langchain_core.documents import Document
        from rank_bm25 import BM25Okapi
        from open_webui.retrieval.utils import BM25Retriever
        import re
        tokenize=lambda text:re.findall(r'\w+',text.casefold())
        chunks=payload['chunks'];docs=[Document(page_content=c['text'],metadata={'page':c['page'],'chunk':i}) for i,c in enumerate(chunks)]
        tokens=[tokenize(c['text']) for c in chunks];query=tokenize(payload['query'])
        if not query:raise ValueError('Enter a question to search the document')
        engine=BM25Okapi(tokens)
        retriever=BM25Retriever(docs=docs,vectorizer=engine,k=min(4,len(docs)))
        matches=retriever.invoke(' '.join(query))
        # Native retrieval ranks by words; disclose unmatched questions rather than invent relevance.
        words=set(query)
        matches=[d for d in matches if words.intersection(tokenize(d.page_content))]
        return {'processor':'Open WebUI','version':version,'method':'BM25 lexical retrieval',
                'matches':[{'text':d.page_content,'page':d.metadata['page'],'chunk':d.metadata['chunk']} for d in matches]}
    raise ValueError('Unsupported internal Open WebUI function')


def run_semantic(payload):
    if payload.get('action')!='semantic':raise ValueError('Unsupported semantic action')
    if payload.get('embedding_model') not in {row['path'] for row in embedding_models(ROOT)}:raise ValueError('Local embedding model is unavailable')
    run_basic({'action':'device'})
    from sentence_transformers import SentenceTransformer,util
    from open_webui.retrieval.utils import get_embedding_function
    model=SentenceTransformer(payload['embedding_model'],device='cpu',local_files_only=True,trust_remote_code=False,model_kwargs={'use_safetensors':True})
    embed=get_embedding_function('',payload['embedding_model'],model,'','',8)
    chunks=payload['chunks']
    vectors=asyncio.run(embed([payload['query']]+[row['text'] for row in chunks]))
    matches=util.semantic_search(__import__('torch').tensor(vectors[:1]),__import__('torch').tensor(vectors[1:]),top_k=min(4,len(chunks)))[0]
    return {'processor':'Open WebUI','version':os.environ['STRATA_OPEN_WEBUI_VERSION'],'method':'Open WebUI local embeddings · cosine retrieval','embedding_model':Path(payload['embedding_model']).name,'matches':[{'text':chunks[row['corpus_id']]['text'],'page':chunks[row['corpus_id']]['page'],'chunk':row['corpus_id'],'score':row['score']} for row in matches]}


def run_ocr(payload):
    if payload.get('action')!='ocr_extract' or payload.get('mime')!='application/pdf':raise ValueError('OCR supports PDF only')
    models=ocr_models(ROOT)
    if not models:raise ValueError('Local OCR weights are unavailable')
    import importlib.metadata
    if importlib.metadata.version('open-webui')!=os.environ['STRATA_OPEN_WEBUI_VERSION']:raise ValueError('Open WebUI version changed; validate this binding again')
    from pypdf import PdfReader
    from rapidocr import RapidOCR
    from open_webui.retrieval.loaders.pdf import PDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    pdf=PdfReader(payload['path'])
    if pdf.is_encrypted or len(pdf.pages)>100:raise ValueError('PDF must be unencrypted and at most 100 pages')
    pixels=0
    for page in pdf.pages:
        resources=page.get('/Resources',{});resources=resources.get_object() if hasattr(resources,'get_object') else resources
        objects=resources.get('/XObject',{});objects=objects.get_object() if hasattr(objects,'get_object') else objects
        for image in objects.values():
            image=image.get_object()
            if image.get('/Subtype')=='/Image':
                count=int(image.get('/Width',0))*int(image.get('/Height',0));pixels+=count
                if count>16*1024**2 or pixels>100*1024**2:raise ValueError('PDF images exceed the local OCR pixel budget')
    settings={key+'.model_path':path for key,path in models.items()};settings.update({'EngineConfig.onnxruntime.use_cuda':False,'EngineConfig.onnxruntime.use_dml':False})
    loader=PDFLoader(payload['path'],extract_images=True,mode='page');loader.ocr=RapidOCR(params=settings)
    docs=loader.load()
    if sum(len(row.page_content) for row in docs)>1000000:raise ValueError('OCR text exceeds one million characters')
    chunks=RecursiveCharacterTextSplitter(chunk_size=1800,chunk_overlap=180).split_documents(docs)
    if not chunks or not any(row.page_content.strip() for row in chunks):raise ValueError('No readable text after local OCR')
    return {'processor':'Open WebUI','version':os.environ['STRATA_OPEN_WEBUI_VERSION'],'pages':len(docs),'ocr':True,'method':'Open WebUI PDFLoader · local RapidOCR CPU','chunks':[{'text':row.page_content,'page':row.metadata['page']+1 if isinstance(row.metadata.get('page'),int) else None} for row in chunks]}


import asyncio,inspect
sys.path.insert(0,str(Path(__file__).resolve().parent))
sys.path.insert(0,str(ROOT))
from open_webui_runtime import embedding_models,ocr_models

def contract():
    import importlib.metadata,torch
    from open_webui.retrieval.loaders.main import Loader
    from open_webui.retrieval.loaders.pdf import PDFLoader
    from open_webui.retrieval.utils import BM25Retriever,get_embedding_function
    from rapidocr import RapidOCR
    from sentence_transformers import SentenceTransformer
    from open_webui.utils.context_compaction import _find_compaction_boundary,_estimate_messages_tokens
    version=importlib.metadata.version('open-webui')
    if version!=os.environ['STRATA_OPEN_WEBUI_VERSION']:raise ValueError('Candidate version changed')
    if torch.version.cuda is not None or torch.version.hip is not None:raise ValueError('Document runtime must remain CPU only')
    inspect.signature(Loader).bind({})
    inspect.signature(Loader.load).bind(None,'name','text/plain','path')
    inspect.signature(PDFLoader).bind('path',extract_images=True,mode='page')
    inspect.signature(BM25Retriever.invoke).bind(None,'query')
    inspect.signature(get_embedding_function).bind('','',None,'','',8)
    inspect.signature(RapidOCR).bind(params={})
    inspect.signature(SentenceTransformer).bind('model',device='cpu',local_files_only=True,trust_remote_code=False,model_kwargs={'use_safetensors':True})
    inspect.signature(_find_compaction_boundary).bind([],retention_percentage=40)
    inspect.signature(_estimate_messages_tokens).bind([])
    return {'version':version,'torch':torch.__version__,'device':'cpu','contracts':['extract','search','context','semantic','ocr'],'scope':'Native imports and call signatures only; no document or model processing'}

def run(payload):
    if payload.get('action')=='contract':return contract()
    if payload.get('action')=='semantic':return run_semantic(payload)
    if payload.get('action')=='ocr_extract':return run_ocr(payload)
    return run_basic(payload)

if __name__=='__main__':
    try:
        payload=json.loads(sys.stdin.buffer.read(2*1024*1024+1))
        print('STARGATE_RESULT:'+json.dumps(run(payload),ensure_ascii=True),flush=True)
    except Exception as error:
        print('STARGATE_RESULT:'+json.dumps({'error':str(error)},ensure_ascii=True),flush=True)
        raise SystemExit(1)
