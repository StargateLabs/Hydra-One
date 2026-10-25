"""Isolated gfx1100 experiment: enable the existing S=1 V3 read only at T<=6.

The disabled S=2 implementation is never enabled. Installed sources/binaries stay intact.
Builds parity and device probes first; model use requires separate numerical validation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'output/research/source-hc-small-window-01403'
BUILD=ROOT/'build-hc-small-window-01403'
# This entry point used to regenerate the manifest, which could erase the
# quarantine flag. Reject before writing sources/manifests or invoking CMake.
if (ROOT/'output/verification/hc-small-gpu-incident.json').exists():
    raise SystemExit('HC small-window quarantined after GPU launch failure 719; source regeneration and build are blocked pending diagnosed repair.')
cache={}
for line in (ROOT/'build-hip-control-01403/CMakeCache.txt').read_text().splitlines():
    if line.startswith(('#','//')) or ':' not in line or '=' not in line:continue
    name,rest=line.split(':',1);kind,value=rest.split('=',1);cache[name]=(kind,value)
baseline=Path(cache['CMAKE_HOME_DIRECTORY'][1]).resolve()
if not baseline.is_relative_to(ROOT.resolve()):raise SystemExit('Baseline outside workspace')
original=baseline/'src/kernels/cuda/fused_gr.cu'
source=original.read_text(encoding='utf-8')
needle='static const bool v3 = [] { const char* v = std::getenv("STRATA_GR_V3"); return v != nullptr && std::atoi(v) != 0; }();'
replacement='''// Opt-in gfx1100 experiment: the S=1 pinned kernels need at most 60 KiB at T=6.
    // The original T=8 gate requires 80 KiB and therefore rejects this card.
    static const bool small_window = [] {
#if defined(__HIPCC__)
        const char* flag = std::getenv("STRATA_HC_SMALL_WINDOW");
        if (!flag || flag[0] != '1') return false;
        int device = 0; cudaDeviceProp prop{};
        return cudaGetDevice(&device) == cudaSuccess &&
               cudaGetDeviceProperties(&prop, device) == cudaSuccess &&
               std::strncmp(prop.gcnArchName, "gfx1100", 7) == 0;
#else
        return false;
#endif
    }();
    static const bool v3 = small_window || [] { const char* v = std::getenv("STRATA_GR_V3"); return v != nullptr && std::atoi(v) != 0; }();'''
if source.count(needle)!=1:raise SystemExit('Unexpected release dispatch')
patched=source.replace(needle,replacement)
needle='''int split = -1;
            if (need1 <= limit &&'''
replacement='''int split = -1;
            if (small_window && need6 <= limit &&
                cudaFuncSetAttribute(gr_down_v3_kernel<1, 6, true>, cudaFuncAttributeMaxDynamicSharedMemorySize, need6) == cudaSuccess &&
                cudaFuncSetAttribute(gr_down_v3_kernel<1, 5, true>, cudaFuncAttributeMaxDynamicSharedMemorySize, need5) == cudaSuccess) {
                split = 3;  // S=1, only the pinned T=1..6 specializations
            } else if (need1 <= limit &&'''
if patched.count(needle)!=1:raise SystemExit('Unexpected shared memory gate')
patched=patched.replace(needle,replacement)
needle='const int split = v3 && dev3 >= 0 && dev3 < 64 ? split3[dev3] : -1;'
replacement='''const int selected_split = v3 && dev3 >= 0 && dev3 < 64 ? split3[dev3] : -1;
    const int split = selected_split == 3 ? (n_tok >= 1 && n_tok <= 6 && !q8 ? 1 : -1) : selected_split;
    if (selected_split == 3 && split > 0) {
        static bool announced = false;
        if (!announced) {
            std::fprintf(stderr, "strata HC small-window active: gfx1100 S=1, T<=6; larger windows use the default read\\n");
            announced = true;
        }
    }'''
if patched.count(needle)!=1:raise SystemExit('Unexpected window dispatch')
patched=patched.replace(needle,replacement)
target=SOURCE/'src/kernels/cuda/fused_gr.cu'
if SOURCE.exists():
    previous=json.loads((ROOT/'output/verification/hc-small-window-source.json').read_text())
    if not target.is_file() or hashlib.sha256(target.read_text(encoding='utf-8').encode()).hexdigest()!=previous['patched_sha256']:raise SystemExit('Refuse to overwrite existing experimental edits')
    target.write_text(patched,encoding='utf-8')
else:
    shutil.copytree(baseline,SOURCE,ignore=shutil.ignore_patterns('.git','__pycache__'))
    target.write_text(patched,encoding='utf-8')
# Retain the original max-T and QFUSE contracts, and add six numerical window cases.
parity_baseline=baseline/'src/kernels/gr_parity.cpp'
parity_source=parity_baseline.read_text(encoding='utf-8')
parity_source=parity_source.replace('const uint16_t* d_inject, float eps) {', 'const uint16_t* d_inject, float eps, int T = strata::kernels::kFusedGrMaxT, bool qfuse_check = true) {',1)
parity_source=parity_source.replace('D = N * HC, T = kFusedGrMaxT;', 'D = N * HC;',1)
parity_source=parity_source.replace('static const bool v3 = [] { const char* v = std::getenv("STRATA_GR_V3"); return v != nullptr && std::atoi(v) != 0; }();', 'const bool v3 = (!qfuse_check && T <= 6 && std::getenv("STRATA_HC_SMALL_WINDOW")) || [] { const char* v = std::getenv("STRATA_GR_V3"); return v != nullptr && std::atoi(v) != 0; }();',1)
parity_source=parity_source.replace('    {\n        uint8_t *d_q = nullptr, *d_ref = nullptr;', '    if (qfuse_check) {\n        uint8_t *d_q = nullptr, *d_ref = nullptr;',1)
parity_source=parity_source.replace('bad += fused_multi_lds_parity(dN, dD, dU, dJ, eps);', 'bad += fused_multi_lds_parity(dN, dD, dU, dJ, eps);\n        if (std::getenv("STRATA_HC_SMALL_WINDOW")) for (int window = 1; window <= 6; ++window) bad += fused_multi_lds_parity(dN, dD, dU, dJ, eps, window, false);',1)
parity_target=SOURCE/'src/kernels/gr_parity.cpp'
if parity_target.read_text(encoding='utf-8') not in (parity_baseline.read_text(encoding='utf-8'),parity_source):
    raise SystemExit('Refuse to overwrite unknown parity edits')
parity_target.write_text(parity_source,encoding='utf-8')
manifest=dict(baseline=str(baseline),source=str(SOURCE),build=str(BUILD),
              original_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),patched_sha256=hashlib.sha256(patched.encode()).hexdigest(),
              parity_sha256=hashlib.sha256(parity_source.encode()).hexdigest(),scope='gfx1100 S=1 pinned T<=6; default unchanged; S=2 remains disabled',model_tested=False,numerical_validated=False)
(ROOT/'output/verification/hc-small-window-source.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
names=['CMAKE_BUILD_TYPE','CMAKE_C_COMPILER','CMAKE_CXX_COMPILER','CMAKE_HIP_COMPILER','CMAKE_HIP_COMPILER_ROCM_ROOT',
       'CMAKE_HIP_ARCHITECTURES','CMAKE_HIP_FLAGS','CMAKE_PREFIX_PATH','CMAKE_RC_COMPILER','CMAKE_MAKE_PROGRAM']
names += [name for name,(kind,_) in cache.items() if name.startswith('STRATA_') and kind!='INTERNAL' and name!='STRATA_PLE_FIXTURE_DIR']
args=[str(ROOT/'.venv/Scripts/cmake.exe'),'-G','Ninja','-S',str(SOURCE),'-B',str(BUILD)]
args += ['-D'+name+'='+cache[name][1] for name in names if name in cache]
env=dict(os.environ);env.update(HIP_PLATFORM='amd',HIP_COMPILER='clang',HIP_RUNTIME='rocclr',ROCM_PATH=cache['CMAKE_HIP_COMPILER_ROCM_ROOT'][1],HIP_PATH=cache['CMAKE_HIP_COMPILER_ROCM_ROOT'][1])
env['PATH']=os.pathsep.join([str(Path(cache['CMAKE_RC_COMPILER'][1]).parent),str(Path(cache['CMAKE_HIP_COMPILER'][1]).parent),str(ROOT/'engine'),str(ROOT/'engine/rocm/bin'),env['PATH']])
with (ROOT/'output/verification/hc-small-window-build.log').open('w',encoding='utf-8') as log:
    subprocess.run(args,env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    subprocess.run([args[0],'--build',str(BUILD),'--target','gr_parity','strata-device','-j','8'],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
for dll in (ROOT/'engine').glob('*.dll'):shutil.copy2(dll,BUILD/dll.name)
print('Isolated parity build ready; no model or GPU test started')
