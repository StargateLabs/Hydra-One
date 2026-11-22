"""Build the model engine only after the isolated small-window parity gate passes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build-hc-small-window-01403'
report=json.loads((ROOT/'output/verification/hc-small-window-parity.json').read_text())
if report.get('passed') is not True or report.get('activated') is not True:raise SystemExit('Numerical gate not passed')
manifest=json.loads((ROOT/'output/verification/hc-small-window-source.json').read_text())
if manifest.get('quarantined'):raise SystemExit('Candidate quarantined after GPU fault; engine use is blocked')
source=Path(manifest['source'])/'src/kernels/cuda/fused_gr.cu'
if hashlib.sha256(source.read_text(encoding='utf-8').encode()).hexdigest()!=manifest['patched_sha256']:raise SystemExit('Experimental source identity changed')
cache={}
for line in (BUILD/'CMakeCache.txt').read_text().splitlines():
    if line.startswith(('#','//')) or ':' not in line or '=' not in line:continue
    name,rest=line.split(':',1);_,value=rest.split('=',1);cache[name]=value
env=dict(os.environ);env.update(HIP_PLATFORM='amd',HIP_COMPILER='clang',HIP_RUNTIME='rocclr',ROCM_PATH=cache['CMAKE_HIP_COMPILER_ROCM_ROOT'],HIP_PATH=cache['CMAKE_HIP_COMPILER_ROCM_ROOT'])
env['PATH']=os.pathsep.join([str(Path(cache['CMAKE_RC_COMPILER']).parent),str(Path(cache['CMAKE_HIP_COMPILER']).parent),str(ROOT/'engine'),str(ROOT/'engine/rocm/bin'),env['PATH']])
with (ROOT/'output/verification/hc-small-window-engine-build.log').open('w',encoding='utf-8') as log:
    subprocess.run([str(ROOT/'.venv/Scripts/cmake.exe'),'--build',str(BUILD),'--target','strata','-j','8'],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
for dll in (ROOT/'engine').glob('*.dll'):shutil.copy2(dll,BUILD/dll.name)
manifest.update(numerical_validated=True,model_tested=False,binary_sha256=hashlib.sha256((BUILD/'strata.exe').read_bytes()).hexdigest())
(ROOT/'output/verification/hc-small-window-source.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
print('Isolated engine built; model performance and quality still unmeasured')
