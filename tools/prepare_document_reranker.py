"""Fetch a pinned official Safetensors model; never downloads executable model code."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from serve.configuration import atomic_json
REPO='cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
REVISION='1427fd652930e4ba29e8149678df786c240d8825'
FILES=('config.json','model.safetensors','special_tokens_map.json','tokenizer.json','tokenizer_config.json')
def main():
    metadata=json.load(urllib.request.urlopen('https://huggingface.co/api/models/'+REPO+'/revision/'+REVISION+'?blobs=true',timeout=30))
    if metadata['sha']!=REVISION:raise ValueError('Model revision changed')
    entries={r['rfilename']:r for r in metadata['siblings']}
    folder=ROOT/'models/rerankers/mmarco-mMiniLMv2-L12-H384-v1'/REVISION;folder.mkdir(parents=True,exist_ok=True);proof=[]
    if sum(entries[name].get('size',0) for name in FILES)>512*1024**2:raise ValueError('Reranker exceeds bounded download')
    for name in FILES:
        entry=entries[name];target=folder/name;expected=entry.get('lfs',{}).get('sha256')
        if not target.is_file() or target.stat().st_size!=entry['size'] or expected and hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
            temporary=target.with_suffix(target.suffix+'.part')
            with urllib.request.urlopen('https://huggingface.co/'+REPO+'/resolve/'+REVISION+'/'+name,timeout=60) as response,temporary.open('wb') as output:
                count=0
                while chunk:=response.read(1024*1024):
                    count+=len(chunk)
                    if count>entry['size']:raise ValueError('Download exceeds official size')
                    output.write(chunk)
            if temporary.stat().st_size!=entry['size']:raise ValueError('Incomplete download')
            if expected and hashlib.sha256(temporary.read_bytes()).hexdigest()!=expected:raise ValueError('Model hash mismatch')
            temporary.replace(target)
        proof.append({'name':name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()});print(name,target.stat().st_size,flush=True)
    atomic_json(ROOT/'data/open-webui/reranker.json',{'repo':REPO,'revision':REVISION,'folder':str(folder),'files':proof,'license':'Apache-2.0'})
if __name__=='__main__':main()
