"""Original Open WebUI document/context functions in an owned offline CPU child."""
import json, os, sys, secrets
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
data=ROOT/'data/open-webui/private-runtime'
data.mkdir(parents=True,exist_ok=True)
import importlib.util
package=Path(importlib.util.find_spec('open_webui').origin).parent
os.environ.update(FRONTEND_BUILD_DIR=str(package/'frontend'),STATIC_DIR=str(data/'static'),DATA_DIR=str(data),DATABASE_URL='sqlite:///'+str(data/'webui.db'),
    WEBUI_AUTH='false',WEBUI_SECRET_KEY=secrets.token_hex(32),OFFLINE_MODE='true',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
    ENABLE_VERSION_UPDATE_CHECK='false',ENABLE_PERSISTENT_CONFIG='false',
    CORS_ALLOW_ORIGIN='http://127.0.0.1',DO_NOT_TRACK='true',ANONYMIZED_TELEMETRY='false',USER_AGENT='StargateLab-Internal',
    CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',ROCR_VISIBLE_DEVICES='-1')

def run(payload):
    import importlib.metadata
    version=importlib.metadata.version('open-webui')
    if version!='0.12.0':raise ValueError('Open WebUI version changed; validate this integration again')
    action=payload['action']
    if action=='verify':
        jobs=payload.get('jobs')
        if not isinstance(jobs,dict) or len(jobs)>8:raise ValueError('Invalid verification batch')
        return {key:run(value) for key,value in jobs.items()}
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

if __name__=='__main__':
    try:
        payload=json.loads(sys.stdin.buffer.read(2*1024*1024+1))
        result=run(payload)
        print('STARGATE_RESULT:'+json.dumps(result,ensure_ascii=True),flush=True)
    except Exception as error:
        print('STARGATE_RESULT:'+json.dumps({'error':str(error)},ensure_ascii=True),flush=True)
        raise SystemExit(1)
