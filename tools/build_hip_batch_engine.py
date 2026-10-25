"""Build the isolated HIP-batch experiment from the validated release configuration."""
import json
import os
from pathlib import Path
import subprocess
import shutil
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/research/source-hip-batch-01403'
BUILD=ROOT/'build-hip-batch-01403'
parity=json.loads((ROOT/'output/verification/hip-batch-port-parity.json').read_text())
if parity.get('passed') is not True or parity.get('cases')!=77:raise SystemExit('Batch parity must pass before engine build')
cache={}
for line in (ROOT/'build-hip-control-01403/CMakeCache.txt').read_text().splitlines():
    if line.startswith(('#','//')) or ':' not in line or '=' not in line:continue
    name,rest=line.split(':',1);kind,value=rest.split('=',1);cache[name]=(kind,value)
names=['CMAKE_BUILD_TYPE','CMAKE_C_COMPILER','CMAKE_CXX_COMPILER','CMAKE_HIP_COMPILER','CMAKE_HIP_COMPILER_ROCM_ROOT',
       'CMAKE_HIP_ARCHITECTURES','CMAKE_HIP_FLAGS','CMAKE_PREFIX_PATH','CMAKE_RC_COMPILER','CMAKE_MAKE_PROGRAM']
names += [name for name in cache if name.startswith('STRATA_') and name not in ('STRATA_PLE_FIXTURE_DIR',)]
args=[str(ROOT/'.venv/Scripts/cmake.exe'),'-G','Ninja','-S',str(SOURCE),'-B',str(BUILD)]
args += ['-D'+name+'='+cache[name][1] for name in names]
env=dict(os.environ);env.update(HIP_PLATFORM='amd',HIP_COMPILER='clang',HIP_RUNTIME='rocclr',ROCM_PATH=cache['CMAKE_HIP_COMPILER_ROCM_ROOT'][1],HIP_PATH=cache['CMAKE_HIP_COMPILER_ROCM_ROOT'][1])
env['PATH']=os.pathsep.join([str(Path(cache['CMAKE_RC_COMPILER'][1]).parent),str(Path(cache['CMAKE_HIP_COMPILER'][1]).parent),str(ROOT/'engine'),str(ROOT/'engine/rocm/bin'),env['PATH']])
log=ROOT/'output/verification/hip-batch-engine-build.log'
with log.open('w',encoding='utf-8') as out:
    subprocess.run(args,env=env,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    print('Isolated engine configured; compiling',flush=True)
    subprocess.run([args[0],'--build',str(BUILD),'--target','strata','-j','8'],env=env,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
print('Experimental engine compiled; installed engine untouched',flush=True)
# Windows searches System32 before PATH. Side-by-side DLLs are essential to
# keep the candidate on the same HIP runtime as the operational engine.
for dll in (ROOT/'engine').glob('*.dll'):shutil.copy2(dll,BUILD/dll.name)
