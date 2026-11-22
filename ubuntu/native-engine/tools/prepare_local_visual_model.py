"""Explicit pinned Hugging Face model preparation; generation remains offline."""
import argparse,hashlib,json,shutil,subprocess,urllib.parse,urllib.request,uuid
from pathlib import Path

SUPPORTED=('segmind/tiny-sd','stabilityai/stable-diffusion-xl-base-1.0','stabilityai/stable-diffusion-xl-refiner-1.0','damo-vilab/text-to-video-ms-1.7b','ali-vilab/text-to-video-ms-1.7b')

def select_files(repo,metadata):
    if repo not in SUPPORTED:
        raise ValueError('Choose a documented supported model repository')
    files=[];prefer_fp16=repo.endswith('text-to-video-ms-1.7b') or repo.startswith('stabilityai/stable-diffusion-xl-')
    names={row['rfilename'] for row in metadata['siblings']}
    components={'scheduler','text_encoder','text_encoder_2','tokenizer','tokenizer_2','unet','vae'}
    for row in metadata['siblings']:
        name=row['rfilename'];path=Path(name)
        if path.is_absolute() or '..' in path.parts or ':' in name:raise ValueError('Invalid model file path')
        if '/' in name and name.split('/')[0] not in components:continue
        if name.endswith(('.bin','.safetensors')):
            if '/' not in name:continue
            if path.name.startswith(('openvino_','onnx_')):continue
            base=name.replace('.fp16.','.')
            if base.endswith('.bin'):base=base[:-4]+'.safetensors'
            if path.name=='pytorch_model.bin' and any(candidate in names for candidate in (str(path.parent/'model.safetensors').replace('\\','/'),str(path.parent/'model.fp16.safetensors').replace('\\','/'))):continue
            fp16=base.replace('.safetensors','.fp16.safetensors')
            chosen=fp16 if prefer_fp16 and fp16 in names else base if base in names else base[:-12]+'.bin'
            if name!=chosen:continue
        if name.endswith(('.json','.txt','.md','.safetensors','.model','.bin')):
            files.append((name,row.get('size') or row.get('lfs',{}).get('size') or 0,row.get('lfs',{}).get('sha256')))
    return files

def prepare(repo, destination, limit=None, plan_only=False):
    if repo not in SUPPORTED:raise ValueError('Choose a documented supported model repository')
    root=Path(__file__).resolve().parents[1];destination=Path(destination).resolve()
    if not destination.is_relative_to((root/'models').resolve()) or destination==(root/'models').resolve():raise ValueError('Model destination must be within project models')
    if destination.exists():raise ValueError('Model destination already exists; existing models are preserved')
    with urllib.request.urlopen('https://huggingface.co/api/models/'+repo+'?blobs=true',timeout=30) as response:metadata=json.load(response)
    revision=metadata['sha'];files=select_files(repo,metadata)
    prefer_fp16=repo.endswith('text-to-video-ms-1.7b') or repo.startswith('stabilityai/stable-diffusion-xl-')
    if limit is None:limit=(10 if repo.startswith('stabilityai/stable-diffusion-xl-') else 5)*1024**3
    total=sum(size for _,size,_ in files)
    if not any(name.endswith(('.bin','.safetensors')) for name,_,_ in files):raise ValueError('No model weights available')
    if not total or total>limit:raise ValueError('Selected model exceeds preparation budget: '+str(total))
    if shutil.disk_usage(root).free<total+5*1024**3:raise ValueError('Insufficient disk space including protected reserve')
    if plan_only:return {'repository':'https://huggingface.co/'+repo,'revision':revision,'download_bytes':total,'budget_bytes':limit,'files':[name for name,_,_ in files],'installed':False}
    final_destination=destination;destination=destination.with_name(destination.name+'.candidate-'+uuid.uuid4().hex)
    destination.mkdir(parents=True,exist_ok=True);proof=[]
    for name,size,expected in files:
        local_name=name.replace('.fp16.safetensors','.safetensors') if prefer_fp16 else name
        target=destination/local_name;target.parent.mkdir(parents=True,exist_ok=True);partial=target.with_name(target.name+'.partial')
        digest=hashlib.sha256();count=0
        try:
            with urllib.request.urlopen(f'https://huggingface.co/{repo}/resolve/{revision}/'+urllib.parse.quote(name,safe='/'),timeout=60) as response,partial.open('wb') as output:
                while chunk:=response.read(1024*1024):
                    count+=len(chunk)
                    if count>limit or size and count>size:raise ValueError('Model file exceeds declared size')
                    output.write(chunk);digest.update(chunk)
            if size and count!=size or expected and digest.hexdigest()!=expected:raise ValueError('Model file checksum or size mismatch')
            partial.replace(target);proof.append({'publisher_file':name,'file':local_name,'bytes':count,'sha256':digest.hexdigest()})
        finally:partial.unlink(missing_ok=True)
    binaries=list(destination.rglob('*.bin'))
    if binaries:
        runtime=Path.home()/'.unsloth/studio/unsloth_studio/Scripts/python.exe'
        if not runtime.is_file():raise ValueError('Torch runtime required for weights-only Safetensors conversion')
        code="import sys,torch;from safetensors.torch import save_file;from pathlib import Path;p=Path(sys.argv[1]);state=torch.load(p,map_location='cpu',weights_only=True);target=p.with_name('model.safetensors') if p.name=='pytorch_model.bin' else p.with_suffix('.safetensors');save_file({k:v.contiguous() for k,v in state.items()},str(target),metadata={'format':'pt'})"
        for binary in binaries:
            subprocess.run([str(runtime),'-c',code,str(binary)],check=True,timeout=60)
    index=destination/'model_index.json';data=json.loads(index.read_text())
    # These optional components were deliberately excluded. Preserve the publisher's original index.
    (destination/'model_index.publisher.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    data['safety_checker']=[None,None];data['feature_extractor']=[None,None];data['requires_safety_checker']=False
    index.write_text(json.dumps(data,indent=2),encoding='utf-8')
    report={'repository':'https://huggingface.co/'+repo,'revision':revision,'license':(metadata.get('cardData') or {}).get('license'),
            'files':proof,'local_index_changes':'Optional safety checker and feature extractor omitted; publisher index preserved','generation_downloads':False}
    (destination/'provenance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if final_destination.exists():raise ValueError('Model destination appeared during preparation; candidate preserved separately')
    destination.rename(final_destination);return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('repository',choices=SUPPORTED);parser.add_argument('destination');parser.add_argument('--plan',action='store_true');args=parser.parse_args()
    result=prepare(args.repository,args.destination,plan_only=args.plan);print(json.dumps(result if args.plan else {'revision':result['revision'],'files':len(result['files'])}))
