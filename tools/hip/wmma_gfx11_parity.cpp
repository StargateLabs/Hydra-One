#include "hydra/kernels/hip_wmma_gfx11.hpp"
#include <cstdio>
#include <cmath>
#include <vector>
using namespace strata::kernels::gfx11;
#define CHECK(x) do { auto e=(x); if(e!=hipSuccess){std::fprintf(stderr,"%s: %s\n",#x,hipGetErrorString(e));return 2;} } while(0)
__global__ void multiply(const float* a,const float* b,const float* c,float* d,int bf) {
    const int l=threadIdx.x&31,col=l&15,half=l>>4;
    H8 ah,bh; S8 as,bs; F8 cc;
#pragma unroll
    for(int i=0;i<8;++i){
        ah[i]=(_Float16)a[col*16+half*8+i]; bh[i]=(_Float16)b[(half*8+i)*16+col];
        union{float f;unsigned u;} ua,ub;
        ua.f=a[col*16+half*8+i]; ub.f=b[(half*8+i)*16+col];
        as[i]=(short)(ua.u>>16); bs[i]=(short)(ub.u>>16);
        cc[i]=c[(half*8+i)*16+col];
    }
    F8 out=bf?bf16(as,bs,cc):f16(ah,bh,cc);
#pragma unroll
    for(int i=0;i<8;++i)d[(half*8+i)*16+col]=out[i];
}
int main(){
    hipDeviceProp_t prop{}; CHECK(hipGetDeviceProperties(&prop,0));
    std::printf("device %s %s\n",prop.name,prop.gcnArchName);
    float *a,*b,*c,*d;
    CHECK(hipMalloc(&a,1024));CHECK(hipMalloc(&b,1024));CHECK(hipMalloc(&c,1024));CHECK(hipMalloc(&d,1024));
    std::vector<float> A(256),B(256),C(256),D(256); int bad=0;
    for(int trial=0;trial<32;++trial){
        for(int i=0;i<256;++i){A[i]=((i*7+trial*3)%23-11)*.125f;B[i]=((i*11+trial*5)%19-9)*.25f;C[i]=(i+trial)*.03125f;}
        CHECK(hipMemcpy(a,A.data(),1024,hipMemcpyHostToDevice));CHECK(hipMemcpy(b,B.data(),1024,hipMemcpyHostToDevice));CHECK(hipMemcpy(c,C.data(),1024,hipMemcpyHostToDevice));
        for(int bf=0;bf<2;++bf){
            multiply<<<1,32>>>(a,b,c,d,bf);CHECK(hipGetLastError());CHECK(hipDeviceSynchronize());CHECK(hipMemcpy(D.data(),d,1024,hipMemcpyDeviceToHost));
            for(int r=0;r<16;++r)for(int n=0;n<16;++n){float ref=C[r*16+n];for(int k=0;k<16;++k)ref+=A[r*16+k]*B[k*16+n];
                if(!std::isfinite(D[r*16+n]) || std::fabs(D[r*16+n]-ref)>.0001f){if(bad<4)std::printf("FAIL trial=%d bf=%d r=%d n=%d got=%f ref=%f\n",trial,bf,r,n,D[r*16+n],ref);++bad;}}
        }
    }
    CHECK(hipFree(a));CHECK(hipFree(b));CHECK(hipFree(c));CHECK(hipFree(d));
    std::printf("nonuniform matrix+accumulator parity: %s (%d mismatches / 16384 values)\n",bad?"FAIL":"PASS",bad);
    return bad?1:0;
}
