"""Download pinned public T5 conditioning into an owned offline Hub cache."""
import hashlib,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from serve.configuration import atomic_json

def main(folder,encoder="t5-large"):
 if encoder=="mert":return prepare_mert()
 if encoder not in ("t5-base","t5-large"):raise ValueError("Unsupported T5 encoder")
 from huggingface_hub import HfApi,snapshot_download
 folder=Path(folder).resolve();base=ROOT/'output/updates/audiocraft-candidates'
 if not folder.is_relative_to(base.resolve()):raise ValueError('Invalid conditioning candidate folder')
 repo='google-t5/'+encoder;info=HfApi(token=False).model_info(repo,files_metadata=True,timeout=20)
 if info.gated:raise ValueError('Conditioning requires original account/license access')
 files=[row for row in info.siblings if row.rfilename in ('config.json','tokenizer_config.json','special_tokens_map.json','spiece.model','model.safetensors')]
 if not any(row.rfilename=='model.safetensors' for row in files):raise ValueError('Original Safetensors conditioning weights unavailable')
 if sum(row.size or 0 for row in files)>4*1024**3:raise ValueError('Conditioning exceeds 4 GiB')
 cache=folder/'conditioning-cache';snapshot=Path(snapshot_download(repo_id=repo,revision=info.sha,token=False,cache_dir=str(cache),allow_patterns=[row.rfilename for row in files],max_workers=2))
 hashes={}
 for row in files:
  path=snapshot/row.rfilename
  if not path.resolve().is_relative_to(cache.resolve()) or path.stat().st_size!=row.size:raise ValueError('Conditioning file changed')
  with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  if row.lfs and digest!=row.lfs.sha256:raise ValueError('Conditioning hash mismatch')
  if row.rfilename=='model.safetensors' and not row.lfs:raise ValueError('Original weight hash unavailable')
  hashes[row.rfilename]=digest
 canonical=cache/('models--google-t5--'+encoder);alias=cache/('models--'+encoder)
 if canonical.is_dir() and not alias.exists():canonical.rename(alias)
 refs=alias/'refs';refs.mkdir(parents=True,exist_ok=True);(refs/'main').write_text(info.sha,encoding='utf-8')
 atomic_json(ROOT/('data/audiocraft-conditioning.json' if encoder=='t5-large' else 'data/audiocraft-conditioning-t5-base.json'),{'repository':repo,'revision':info.sha,'cache':str(cache),'sha256':hashes,'license':(info.card_data or {}).get('license'),'validated':True,'scope':'Original file sizes and hashes; no inference'})
def prepare_mert():
 from huggingface_hub import HfApi,snapshot_download
 from serve.audiocraft_conditioning import selected_cache
 cache=selected_cache(ROOT,'t5-base');repo='m-a-p/MERT-v1-95M';revision='12af15fef9d0ac838c3f475bfbbf26d2060dd4f5'
 names=['config.json','configuration_MERT.py','modeling_MERT.py','preprocessor_config.json','pytorch_model.bin']
 info=HfApi(token=False).model_info(repo,revision=revision,files_metadata=True,timeout=20)
 folder=Path(snapshot_download(repo,revision=revision,token=False,cache_dir=str(cache),allow_patterns=names,max_workers=2))
 hashes={}
 for name in names:
  path=folder/name;entry=next(row for row in info.siblings if row.rfilename==name)
  with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
  if path.stat().st_size!=entry.size or entry.lfs and digest!=entry.lfs.sha256:raise ValueError('MERT size/hash mismatch')
  hashes[name]=digest
 ref=cache/'models--m-a-p--MERT-v1-95M/refs/main';ref.parent.mkdir(parents=True,exist_ok=True);ref.write_text(revision)
 atomic_json(ROOT/'data/audiocraft-style-dependency.json',{'repository':repo,'revision':revision,'cache':str(cache),'folder':str(folder),'files':hashes,'license':'CC-BY-NC-4.0'})

if __name__=='__main__':main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else "t5-large")
