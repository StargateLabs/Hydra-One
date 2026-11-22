"""Build the archived official release in isolation; never installs the executable."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--configure-only',action='store_true')
    a=p.parse_args()
    archive=ROOT/'output/research/source-v0.1.40.3'
    manifest=json.loads((archive/'manifest.json').read_text())
    source=archive/f"Strata-{manifest['commit']}"
    dependency=json.loads((ROOT/'output/research/llama-pinned/manifest.json').read_text())
    llama=ROOT/'output/research/llama-pinned'/f"llama.cpp-{dependency['commit']}"
    if dependency['commit'] not in (source/'CMakeLists.txt').read_text():raise RuntimeError('Dependency does not match source pin')
    if hashlib.sha256((archive/'source.zip').read_bytes()).hexdigest()!=manifest['sha256']:raise RuntimeError('Source archive hash differs')
    spec=importlib.util.spec_from_file_location('hip_build',ROOT/'spikes/004-compila-motore/compila_motore.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    rocm,libs,bitcode=helper.trova_rocm();rc=helper.trova_rc();cmake,ninja=helper.cmake_ninja()
    if not all((rocm,rc,cmake,ninja)):raise RuntimeError('Compiler prerequisite missing')
    path=lambda x:str(x).replace('\\','/')
    env=dict(os.environ)
    env.update(HIP_PLATFORM='amd',HIP_COMPILER='clang',HIP_RUNTIME='rocclr',ROCM_PATH=path(rocm),HIP_PATH=path(rocm),RC=rc)
    env['PATH']=os.pathsep.join([str(Path(rc).parent),str(rocm/'lib/llvm/bin'),str(ROOT/'engine/rocm/bin'),str(helper.RV/'Scripts'),env.get('PATH','')])
    build=ROOT/'build-hip-control-01403'
    logdir=ROOT/'output/verification';logdir.mkdir(parents=True,exist_ok=True)
    command=[str(cmake),'-G','Ninja','-S',str(source),'-B',str(build),f'-DCMAKE_MAKE_PROGRAM={path(ninja)}','-DCMAKE_BUILD_TYPE=Release','-DSTRATA_ENABLE_HIP=ON','-DSTRATA_ENABLE_CUDA=OFF','-DSTRATA_BUILD_TESTS=OFF','-DSTRATA_PREFILL_MMQ=ON','-DSTRATA_NATIVE_EXPERTS=ON','-DSTRATA_PORTABLE=ON','-DCMAKE_HIP_ARCHITECTURES=gfx1100',f'-DCMAKE_C_COMPILER={path(rocm / "lib/llvm/bin/clang.exe")}',f'-DCMAKE_CXX_COMPILER={path(rocm / "lib/llvm/bin/clang++.exe")}',f'-DCMAKE_HIP_COMPILER={path(rocm / "lib/llvm/bin/clang++.exe")}',f'-DCMAKE_HIP_COMPILER_ROCM_ROOT={path(rocm)}','-DCMAKE_PREFIX_PATH='+';'.join(map(path,[rocm,*libs])),f'-DCMAKE_HIP_FLAGS=--rocm-path={path(rocm)} --rocm-device-lib-path={path(bitcode)}',f'-DSTRATA_GGML_DIR={path(llama)}',f'-DCMAKE_RC_COMPILER={rc}']
    with (logdir/'aligned-control-configure.log').open('w',encoding='utf-8') as f:subprocess.run(command,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    print('Aligned control configured; operational executable unchanged.',flush=True)
    if a.configure_only:return
    with (logdir/'aligned-control-build.log').open('w',encoding='utf-8') as f:subprocess.run([str(cmake),'--build',str(build),'--target','strata','strata-device','-j','2'],env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
    exe=build/'strata.exe'
    # Match the operational bundle's application-local runtime lookup on Windows.
    # Otherwise the process can terminate before main() with an empty engine log.
    runtime_files = ('amdhip64_7.dll','amd_comgr.dll','msvcp140.dll',
                     'vcruntime140.dll','vcruntime140_1.dll','rocm_kpack.dll')
    runtime_hashes = {}
    for name in runtime_files:
        origin = ROOT/'engine'/name
        if not origin.is_file():
            raise RuntimeError(f'Bundled runtime missing: {name}')
        shutil.copy2(origin, build/name)
        runtime_hashes[name] = hashlib.sha256(origin.read_bytes()).hexdigest()
    result={'source_commit':manifest['commit'],'ggml_commit':dependency['commit'],'exe':str(exe),'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'installed':False,'gpu_tested':False}
    result['runtime_sha256'] = runtime_hashes
    (logdir/'aligned-control-build.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
