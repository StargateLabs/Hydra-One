"""Prepare the original v0.5.6 app's private CPU backend without speech weights.

Workaround for bundled uv 0.12.13's managed-Python minor-link failure and the
release's CUDA-only lock source. Uses the interpreter downloaded by the app,
its bundled uv and frozen dependency graph; changes only the app-private venv.
The supported OMNIVOICE_BACKEND_CMD override avoids a fabricated ready stamp.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from serve.voicestudio import desktop_executable

PROBE='import torch,torchaudio,torchvision,fastapi,uvicorn,omnivoice,faster_whisper,sentencepiece; assert torch.__version__ == "2.8.0+cpu"; assert not torch.cuda.is_available(); print("CPU_BACKEND_IMPORTS_OK",torch.__version__)'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Install dependencies, never speech weights.')
    args=parser.parse_args()
    desktop=desktop_executable()
    if desktop is None:raise RuntimeError('Original VoiceStudio desktop not installed.')
    bundle=desktop.parent/'resources'
    manifest=tomllib.loads((bundle/'pyproject.toml').read_text(encoding='utf-8'))
    if manifest['project']['version']!='0.5.6':raise RuntimeError('This CPU workaround is pinned to VoiceStudio v0.5.6.')
    runtime=Path(os.environ['APPDATA'])/'VoiceStudio/runtime'
    project=runtime/'project';python=project/'.venv/Scripts/python.exe';uv=bundle/'tools/uv.exe'
    if not project.is_dir() or (project/'uv.lock').read_bytes()!=(bundle/'uv.lock').read_bytes():
        raise RuntimeError('Run the original first-launch setup to stage the app-private project and Python first.')
    probe=subprocess.run([str(python),'-c',PROBE],capture_output=True,text=True) if python.is_file() else None
    if not probe or probe.returncode:
        if not args.install:raise RuntimeError('CPU runtime incomplete; --install explicitly enables dependency setup.')
        interpreters=list((runtime/'.python').glob('cpython-3.11.*-windows-x86_64-none/python.exe'))
        if len(interpreters)!=1:raise RuntimeError('Expected one app-downloaded private CPython 3.11 interpreter.')
        environment=os.environ.copy();environment.pop('PYTHONHOME',None);environment.pop('PYTHONPATH',None)
        environment.update(UV_PROJECT_ENVIRONMENT=str(project/'.venv'),UV_CACHE_DIR=str(runtime/'.uv-cache'),UV_PYTHON_INSTALL_DIR=str(runtime/'.python'))
        subprocess.run([str(uv),'sync','--frozen','--no-dev','--no-install-package','torch','--no-install-package','torchaudio','--no-install-package','torchvision','--no-managed-python','--no-python-downloads','--python',str(interpreters[0])],cwd=project,env=environment,check=True)
        subprocess.run([str(uv),'pip','install','--python',str(python),'--index-url','https://download.pytorch.org/whl/cpu','--no-deps','torch==2.8.0+cpu','torchaudio==2.8.0+cpu','torchvision==0.23.0+cpu'],cwd=project,env=environment,check=True)
    subprocess.run([str(python),'-c',PROBE],check=True)
    marker={'lock_sha256':hashlib.sha256((bundle/'uv.lock').read_bytes()).hexdigest(),'torch':'2.8.0+cpu','verified_imports':True,'setup_reason':'v0.5.6 bundled uv Python minor-link failure; private CPU runtime'}
    if args.install:(project/'strata-cpu-runtime.json').write_text(json.dumps(marker,indent=2),encoding='utf-8')
    print(json.dumps({'verified':True,'runtime':str(project),'python':str(python),'launch_via':'OMNIVOICE_BACKEND_CMD','speech_weights_downloaded':False},indent=2))


if __name__=='__main__':main()
