"""Explicit preparation of the project-only OpenVoice conversion environment.

Reuses a selected existing Torch runtime read-only; never changes that runtime.
No weights are downloaded unless --converter is explicitly supplied.
"""
import argparse, hashlib, json, os, subprocess, sys, urllib.request
from pathlib import Path
SOURCE_COMMIT='74a1d147b17a8c3092dd5430504bd83ef6c7eb23'
MODEL_REVISION='f36e7edfe1684461a8343844af60babc2efbb727'
CHECKPOINT_SHA='9652c27e92b6b2a91632590ac9962ef7ae2b712e5c5b7f4c34ec55ee2b37ab9e'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--install',action='store_true');p.add_argument('--converter',action='store_true');p.add_argument('--shared-runtime',type=Path,default=Path(os.environ.get('APPDATA',''))/'VoiceStudio/runtime/project/.venv');a=p.parse_args()
 root=Path(__file__).resolve().parents[1];folder=root/'tools/local-generative-audio';runtime=folder/'.venv';python=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python');shared=a.shared_runtime.resolve();base=shared/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
 if not a.install:print(json.dumps({'installed':python.is_file(),'runtime':str(runtime),'shared_readonly_runtime':str(shared),'converter_download_bytes':131320490}));return
 if not base.is_file():raise ValueError('Select an existing compatible Torch CPU runtime with --shared-runtime')
 folder.mkdir(exist_ok=True);(folder/'.gitignore').write_text('.venv/\n',encoding='utf-8')
 if not python.is_file():subprocess.run([str(base),'-m','venv',str(runtime)],check=True)
 shared_sites=json.loads(subprocess.check_output([str(base),'-c','import site,json;print(json.dumps(site.getsitepackages()))'],text=True))
 sites=json.loads(subprocess.check_output([str(python),'-c','import site,json;print(json.dumps(site.getsitepackages()))'],text=True))
 Path(sites[0],'shared-runtime-readonly.pth').write_text('\n'.join(shared_sites)+'\n',encoding='utf-8')
 subprocess.run([str(python),'-m','pip','install','--no-deps',f'https://github.com/myshell-ai/OpenVoice/archive/{SOURCE_COMMIT}.zip'],check=True)
 subprocess.run([str(python),'-m','pip','install','librosa==0.10.2.post1','eng_to_ipa==0.0.2','inflect==7.0.0','unidecode==1.3.7','pypinyin==0.50.0','cn2an==0.5.22','jieba==0.42.1'],check=True)
 subprocess.run([str(python),'-c','from openvoice.api import ToneColorConverter; import torch,soundfile;print(torch.__version__)'],check=True)
 metadata={'source_repository':'https://github.com/myshell-ai/OpenVoice','source_commit':SOURCE_COMMIT,'shared_runtime_readonly':str(shared),'profile':'conversion-only; no ASR, TTS or watermark downloads','dependency_note':'upstream full-application pins are not used; this profile validates only waveform conversion'}
 if a.converter:
  model=root.parent/'Strata-data/models/audio/conversion/openvoice-v2';model.mkdir(parents=True,exist_ok=True)
  for name,url in [('checkpoint.pth',f'https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/{MODEL_REVISION}/converter/checkpoint.pth'),('config.json',f'https://huggingface.co/myshell-ai/OpenVoiceV2/resolve/{MODEL_REVISION}/converter/config.json'),('LICENSE',f'https://raw.githubusercontent.com/myshell-ai/OpenVoice/{SOURCE_COMMIT}/LICENSE')]:
   target=model/name
   if not target.is_file():
    temporary=target.with_suffix(target.suffix+'.download');urllib.request.urlretrieve(url,temporary);os.replace(temporary,target)
  digest=hashlib.sha256((model/'checkpoint.pth').read_bytes()).hexdigest()
  if digest!=CHECKPOINT_SHA:raise RuntimeError('Official checkpoint SHA256 mismatch')
  provenance={'repository':'https://huggingface.co/myshell-ai/OpenVoiceV2','revision':MODEL_REVISION,'license':'MIT','checkpoint_sha256':digest,'checkpoint_bytes':(model/'checkpoint.pth').stat().st_size}
  (model/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8');metadata['converter']=provenance
 (folder/'runtime.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8');print(json.dumps(metadata))
 probe=json.loads(subprocess.check_output([str(python),'-c',"import torch,json;print(json.dumps({'torch_version':torch.__version__,'cuda_available':torch.cuda.is_available(),'hip_version':torch.version.hip}))"],text=True))
 probe.update(python=str(python),python_sha256=hashlib.sha256(python.read_bytes()).hexdigest(),scope='Actual isolated audio runtime device availability; not speed or quality')
 (root/'data').mkdir(exist_ok=True);(root/'data/generative-audio-runtime.json').write_text(json.dumps(probe,indent=2),encoding='utf-8')
if __name__=='__main__':main()
