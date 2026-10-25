// Copy-only experiment: mapped host reads by compute vs runtime H2D DMA.
// No engine integration; no waiting kernels. Each destination is fully verified.
#include <hip/hip_runtime.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
#if defined(_WIN32)
#include <windows.h>
#endif

static void check(hipError_t rc,const char* op){
    if(rc!=hipSuccess){std::fprintf(stderr,"%s: %s\n",op,hipGetErrorString(rc));throw std::runtime_error(op);}
}
struct Buffers {
    void* host=nullptr;void* device=nullptr;hipStream_t stream=nullptr;
    ~Buffers(){if(stream)(void)hipStreamDestroy(stream);if(device)(void)hipFree(device);if(host)(void)hipHostFree(host);}
};
__global__ void blit(const uint4* src,uint4* dst,size_t n){
    for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<n;i+=size_t(gridDim.x)*blockDim.x)dst[i]=src[i];
}
using Clock=std::chrono::steady_clock;
int main(){
    try {
#if defined(_WIN32)
        char runtime[32768]{};GetModuleFileNameA(GetModuleHandleA("amdhip64_7.dll"),runtime,sizeof(runtime));
        std::fprintf(stderr,"HIP runtime: %s\n",runtime);
#endif
        constexpr size_t capacity=256ull<<20;
        size_t available=0,total=0;check(hipMemGetInfo(&available,&total),"memory info");
        if(available<capacity+(1536ull<<20))throw std::runtime_error("insufficient margin");
        Buffers b;check(hipMalloc(&b.device,capacity),"device allocation");
        check(hipHostMalloc(&b.host,capacity,hipHostMallocMapped),"mapped host allocation");
        void* alias=nullptr;check(hipHostGetDevicePointer(&alias,b.host,0),"mapped alias");
        check(hipStreamCreateWithFlags(&b.stream,hipStreamNonBlocking),"stream");
        auto* input=static_cast<unsigned char*>(b.host);
        for(size_t i=0;i<capacity;++i)input[i]=static_cast<unsigned char>((i*37+(i>>12)*13)&255);
        std::vector<unsigned char> output(capacity);
        for(size_t bytes:{1ull<<20,16ull<<20,64ull<<20,256ull<<20}){
            for(int variant=0;variant<3;++variant){
                std::vector<double> speeds;
                for(int run=0;run<9;++run){
                    check(hipStreamSynchronize(b.stream),"before sync");
                    auto t=Clock::now();
                    if(variant==0)check(hipMemcpyAsync(b.device,b.host,bytes,hipMemcpyHostToDevice,b.stream),"DMA");
                    else {
                        unsigned blocks=variant==1?256:1024;
                        hipLaunchKernelGGL(blit,dim3(blocks),dim3(256),0,b.stream,static_cast<const uint4*>(alias),static_cast<uint4*>(b.device),bytes/sizeof(uint4));
                        check(hipGetLastError(),"blit launch");
                    }
                    check(hipStreamSynchronize(b.stream),"after sync");
                    double seconds=std::chrono::duration<double>(Clock::now()-t).count();
                    if(run>=2)speeds.push_back(bytes/seconds/1e9);
                }
                check(hipMemcpy(output.data(),b.device,bytes,hipMemcpyDeviceToHost),"verify download");
                if(std::memcmp(output.data(),input,bytes)!=0)throw std::runtime_error("payload mismatch");
                std::sort(speeds.begin(),speeds.end());
                std::printf("{\"mode\":\"%s\",\"bytes\":%llu,\"median_gbps\":%.6f,\"best_gbps\":%.6f,\"verified_bytes\":%llu}\n",variant==0?"DMA":variant==1?"compute_256":"compute_1024",static_cast<unsigned long long>(bytes),speeds[3],speeds.back(),static_cast<unsigned long long>(bytes));
                std::fflush(stdout);
            }
        }
    }catch(const std::exception& e){std::fprintf(stderr,"probe rejected: %s\n",e.what());return 1;}
    return 0;
}
