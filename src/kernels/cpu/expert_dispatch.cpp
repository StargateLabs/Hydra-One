// Capability dispatch must stay outside the AVX-512 translation unit.
#include "hydra/kernels/cpu/portable_expert.hpp"
#include "hydra/kernels/cpu/expert_layout.hpp"
#include <stdexcept>
namespace strata::kernels::cpu {
namespace {
void portable_contract() {
    if (expert_oracle_q8_0_enabled())
        throw std::runtime_error("portable planar expert: oracle Q8_0 contract unavailable; legacy contract only");
}
}
void expert_gu_any(const uint8_t* b,const ActQ& a,float* ff,int r0,int r1) {
    if(cpu_avx512_ok()) { s2_expert_gu_rows(b,a,ff,r0,r1);return; }
    portable_contract();portable_gu_rows(b,a,ff,r0,r1);
}
void expert_down_any(const uint8_t* b,const ActQ& a,float* out,int r0,int r1) {
    if(cpu_avx512_ok()) { s2_expert_down_rows(b,a,out,r0,r1);return; }
    portable_contract();portable_down_rows(b,a,out,r0,r1);
}
void expert_cpu_any(const uint8_t* b,const ActQ& a,float* out,ExpertScratch& ws) {
    if(cpu_avx512_ok()) { s2_expert_vnni_q(b,a,out,ws);return; }
    portable_contract();portable_gu_rows(b,a,ws.ff,0,FF);
    act_quant_any(ws.ff,FF,ws.a2);portable_down_rows(b,ws.a2,out,0,H);
}
void expert_gu_multi_any(const uint8_t* b,const ActQ* const* a,int n,float* const* ff,int r0,int r1) {
    if(n<1 || n>MAXT) throw std::invalid_argument("invalid expert token group");
    if(cpu_avx512_ok()) { s2_expert_gu_rows_multi(b,a,n,ff,r0,r1);return; }
    portable_contract();for(int t=0;t<n;++t) portable_gu_rows(b,*a[t],ff[t],r0,r1);
}
void expert_down_multi_any(const uint8_t* b,const ActQ* const* a,int n,float* const* out,int r0,int r1) {
    if(n<1 || n>MAXT) throw std::invalid_argument("invalid expert token group");
    if(cpu_avx512_ok()) { s2_expert_down_rows_multi(b,a,n,out,r0,r1);return; }
    portable_contract();for(int t=0;t<n;++t) portable_down_rows(b,*a[t],out[t],r0,r1);
}
}
