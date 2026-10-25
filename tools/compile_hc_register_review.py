from pathlib import Path
import subprocess,os,json
root=Path.cwd();base=root/'output/research/source-hc-small-window-01403';target=root/'output/research/hc-register-pressure-review';target.mkdir(exist_ok=True)
s=(base/'src/kernels/cuda/fused_gr.cu').read_text();start=s.index('template <int S, int MAX_T = kFusedGrMaxT, bool EXACT_T = false>\n__global__ void __launch_bounds__(THREADS) gr_down_v3_kernel');end=s.index('template <int S, int MAX_T = kFusedGrMaxT, bool EXACT_T = false>\n__global__ void __launch_bounds__(THREADS) gr_up_v3_kernel',start)
region=s[start:end];needle='#pragma unroll\n        for (int q = 0; q < TQS; ++q)';assert region.count(needle)==1
patched=s[:start]+region.replace(needle,'#pragma unroll 1\n        for (int q = 0; q < TQS; ++q)')+s[end:]
(target/'fused_gr.cu').write_text(patched)
sdk=root/'.rocm-win/Lib/site-packages/_rocm_sdk_devel';llvm=sdk/'lib/llvm/bin';args=[str(llvm/'clang++.exe'),'--rocm-path='+str(sdk),'--rocm-device-lib-path='+str(sdk/'lib/llvm/amdgcn/bitcode'),'-O3','-DNDEBUG','-std=c++20','--offload-arch=gfx1100','-DSTRATA_USE_HIP=1','-DSTRATA_WMMA_GFX11=1','-D__HIP_PLATFORM_AMD__=1','-D__HIP_ROCclr__=1','-include',str(base/'include/hydra/hip_compat/cuda_runtime.h')]
for path in [base/'include',base/'include/hydra/hip_compat',base/'third_party/ggml',base/'src/kernels/cuda',sdk/'include']:args+=['-I',str(path)]
args+=['-x','hip','--cuda-device-only','-c',str(target/'fused_gr.cu'),'-o',str(target/'fused_gr-gfx1100.o')]
env=dict(os.environ);env['TMP']=str(target);env['TEMP']=str(target)
result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=180)
(target/'compile.log').write_text(result.stdout+result.stderr);(target/'command.json').write_text(json.dumps(args,indent=2))
print('Offline compilation exit',result.returncode);print((result.stdout+result.stderr)[-1800:]);raise SystemExit(result.returncode)
