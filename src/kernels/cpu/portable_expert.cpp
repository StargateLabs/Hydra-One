// Baseline C++ implementation is a separate translation unit: compiler flags
// for expert.cpp can emit AVX-512 even in apparently scalar helper functions.
#include "hydra/kernels/cpu/portable_expert.hpp"
#include <cmath>
#include <cstring>
namespace strata::kernels::cpu {
namespace {
float half(const uint8_t* p) {
    uint16_t h;std::memcpy(&h,p,2);
    const int exponent=(h>>10)&31, mantissa=h&1023;
    const float value=exponent==0 ? std::ldexp(float(mantissa),-24)
        : exponent==31 ? (mantissa ? NAN : INFINITY)
        : std::ldexp(float(1024+mantissa),exponent-25);
    return h&0x8000 ? -value : value;
}
float dot(const uint8_t* codes,const uint8_t* scales,const ActQ& a,int blocks) {
    float sum=0;
    for(int b=0;b<blocks;++b) {
        const float weight=half(scales+2*b);
        for(int chunk=0;chunk<2;++chunk) {
            int total=0;
            for(int j=0;j<QKA;++j) {
                const int index=chunk*QKA+j;
                const int code=int((codes[b*16+index/4]>>(2*(index%4)))&3)-1;
                total+=code*int(a.q[b*QK+index]);
            }
            sum+=weight*a.scale[2*b+chunk]*float(total);
        }
    }
    return sum;
}
}
void portable_gu_rows(const uint8_t* blob,const ActQ& a,float* ff,int r0,int r1) {
    for(int r=r0;r<r1;++r) {
        const float g=dot(blob+O_GU_CODES+size_t(2*r)*ROW_GU,blob+O_GU_SCALES+size_t(2*r)*SC_GU*2,a,SC_GU);
        const float u=dot(blob+O_GU_CODES+size_t(2*r+1)*ROW_GU,blob+O_GU_SCALES+size_t(2*r+1)*SC_GU*2,a,SC_GU);
        ff[r]=g/(1+std::exp(-g))*u;
    }
}
void portable_down_rows(const uint8_t* blob,const ActQ& a,float* out,int r0,int r1) {
    for(int r=r0;r<r1;++r) out[r]=dot(blob+O_D_CODES+size_t(r)*ROW_D,blob+O_D_SCALES+size_t(r)*SC_D*2,a,SC_D);
}
}
