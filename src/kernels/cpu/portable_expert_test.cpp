// Analytic Q2 planar fixture: all weights and activations are constant. No model or GPU.
#include "hydra/kernels/cpu/portable_expert.hpp"
#include "hydra/kernels/cpu/expert_layout.hpp"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>
namespace c = strata::kernels::cpu;
int main() {
    std::vector<uint8_t> blob(c::BLOB, 0xaa); // four code=2 weights per byte, signed value +1
    const uint16_t scale = 0x1400; // exactly 1/1024
    for (size_t i=c::O_GU_SCALES; i<c::BLOB; i+=2) std::memcpy(blob.data()+i,&scale,2);
    c::ActQ a{}; a.nchunks=c::H/c::QKA;
    for (int i=0;i<c::H;++i) a.q[i]=1;
    for (int i=0;i<a.nchunks;++i) { a.scale[i]=1; a.sum[i]=32; a.hx[i]=32; }
    float ff[c::FF],out[c::H];
    c::portable_gu_rows(blob.data(),a,ff,0,c::FF);
    const float gate=float(c::H)/1024;
    const float expected=gate/(1+std::exp(-gate))*gate;
    for (float v:ff) if (std::fabs(v-expected)>1e-5f) return 1;
    c::portable_down_rows(blob.data(),a,out,0,c::H);
    for (float v:out) if (std::fabs(v-float(c::FF)/1024)>1e-6f) return 2;
    // Nonidentical activation chunks and negative codes expose swapped chunk/scaling bugs.
    a.scale[0]=2;a.q[0]=-3;
    c::portable_gu_rows(blob.data(),a,ff,0,1);
    const float changed=(float(c::H)+24)/1024;
    if (std::fabs(ff[0]-changed/(1+std::exp(-changed))*changed)>1e-5f) return 3;
    // The same entry points used by the pool, with automatic capability dispatch.
    float dispatched[c::FF];c::expert_gu_any(blob.data(),a,dispatched,0,c::FF);
    c::portable_gu_rows(blob.data(),a,ff,0,c::FF);
    for(int r=0;r<c::FF;++r) if(std::fabs(ff[r]-dispatched[r])>1e-4f) return 4;
    const c::ActQ* acts[2]={&a,&a};float other[c::FF];float* grouped[2]={dispatched,other};
    c::expert_gu_multi_any(blob.data(),acts,2,grouped,0,c::FF);
    for(int r=0;r<c::FF;++r) if(std::fabs(ff[r]-other[r])>1e-4f) return 5;
    c::ExpertScratch scratch{};c::expert_cpu_any(blob.data(),a,out,scratch);
    for(float value:out) if(!std::isfinite(value)) return 6;
    std::printf("selected kernel: %s; real model inference NOT_EXECUTED\n",c::cpu_avx512_ok()?"AVX512":"SCALAR_PLANAR_Q2 + AVX2_ACTIVATION");
    std::printf("portable scalar planar Q2: analytic gate/up/down and chunk scaling PASS; no model inference\n");
    return 0;
}
