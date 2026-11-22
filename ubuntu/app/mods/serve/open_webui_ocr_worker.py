"""Use the installed original PDF loader with explicitly local RapidOCR weights."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import open_webui_worker as original
from open_webui_runtime import ocr_models

def run(payload):
    if payload.get('action')!='ocr_extract' or payload.get('mime')!='application/pdf':raise ValueError('OCR supports PDF only')
    models=ocr_models(original.ROOT)
    if not models:raise ValueError('Local OCR weights are unavailable')
    import importlib.metadata
    if importlib.metadata.version('open-webui')!='0.12.0':raise ValueError('Open WebUI version changed; validate this binding again')
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
    return {'processor':'Open WebUI','version':'0.12.0','pages':len(docs),'ocr':True,'method':'Open WebUI PDFLoader · local RapidOCR CPU','chunks':[{'text':row.page_content,'page':row.metadata['page']+1 if isinstance(row.metadata.get('page'),int) else None} for row in chunks]}

if __name__=='__main__':
    try:
        payload=json.loads(sys.stdin.buffer.read(2*1024*1024+1));result=run(payload)
        print('STARGATE_RESULT:'+json.dumps(result,ensure_ascii=True),flush=True)
    except Exception as error:
        print('STARGATE_RESULT:'+json.dumps({'error':str(error)},ensure_ascii=True),flush=True);raise SystemExit(1)
