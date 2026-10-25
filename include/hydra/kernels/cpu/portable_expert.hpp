#pragma once
#include "hydra/kernels/cpu/expert.hpp"
namespace strata::kernels::cpu {
// Explicit scalar legacy planar-Q2 implementation. No AVX-512 instructions,
// no allocation, and no claim of native GGUF or oracle-Q8_0 compatibility.
void portable_gu_rows(const uint8_t*,const ActQ&,float*,int,int);
void portable_down_rows(const uint8_t*,const ActQ&,float*,int,int);
void expert_cpu_any(const uint8_t*,const ActQ&,float*,ExpertScratch&);
void expert_gu_any(const uint8_t*,const ActQ&,float*,int,int);
void expert_down_any(const uint8_t*,const ActQ&,float*,int,int);
void expert_gu_multi_any(const uint8_t*,const ActQ* const*,int,float* const*,int,int);
void expert_down_multi_any(const uint8_t*,const ActQ* const*,int,float* const*,int,int);
}
