"""Compile a standalone HIP copy probe; never replace the engine."""
from pathlib import Path
import os
import subprocess
import sys
import shutil
ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/'.rocm-win/Lib/site-packages/_rocm_sdk_devel'
CORE=ROOT/'.rocm-win/Lib/site-packages/_rocm_sdk_core'
parity='--batch-parity' in sys.argv
out=ROOT/('output/verification/hip-batch-port-parity.exe' if parity else 'output/verification/host-blit-probe.exe')
source=ROOT/('tools/hip/hip_batch_port_parity.cpp' if parity else 'tools/hip/host_blit_probe.cpp')
command=[str(DEV/'lib/llvm/bin/clang++.exe'),'-x','hip','--offload-arch=gfx1100',
    '--rocm-path='+str(DEV),'--rocm-device-lib-path='+str(CORE/'lib/llvm/amdgcn/bitcode'),
    '-I'+str(CORE/'include'),'-L'+str(CORE/'lib'),'-O2','-std=c++17',
    str(source),'-lamdhip64','-o',str(out)]
if parity:
    include=ROOT/'output/research/source-hip-batch-01403/include'
    command[1:1]=['-DSTRATA_USE_HIP=1','-I'+str(include/'strata/hip_compat'),'-I'+str(include)]
run=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
(out.with_suffix('.build.log')).write_text(run.stdout+run.stderr,encoding='utf-8')
if run.returncode:raise SystemExit('Standalone build failed; inspect host-blit-probe.build.log')
for dll in (ROOT/'engine').glob('*.dll'):shutil.copy2(dll,out.parent/dll.name)
print('Standalone HIP blit probe compiled')
