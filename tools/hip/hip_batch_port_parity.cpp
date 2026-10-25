// Exercise the actual isolated Strata helper, including failed and partial batch fallback.
#include <hip/hip_runtime.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>
#if defined(_WIN32)
#include <windows.h>
#endif
static unsigned batch_calls=0;
static int inject_failure=0;
static hipError_t counted_batch(void** d,void** s,size_t* b,size_t n,hipMemcpyAttributes* a,size_t* ai,size_t na,size_t* failure,hipStream_t stream){
    ++batch_calls;
    if(inject_failure){
        if(inject_failure==2){auto e=hipMemcpyAsync(d[0],s[0],b[0],hipMemcpyDefault,stream);if(e!=hipSuccess)return e;}
        return hipErrorNotSupported;
    }
    return hipMemcpyBatchAsync(d,s,b,n,a,ai,na,failure,stream);
}
#define hipMemcpyBatchAsync counted_batch
#include "hydra/core/dma_batch.hpp"
#undef hipMemcpyBatchAsync
static void ck(hipError_t e){if(e!=hipSuccess)throw std::runtime_error(hipGetErrorString(e));}
struct Resources{void* h=nullptr;void* d=nullptr;hipStream_t stream=nullptr;~Resources(){if(stream)(void)hipStreamDestroy(stream);if(d)(void)hipFree(d);if(h)(void)hipHostFree(h);}};
int main(){try{
#if defined(_WIN32)
    char runtime[32768]{};GetModuleFileNameA(GetModuleHandleA("amdhip64_7.dll"),runtime,sizeof(runtime));std::fprintf(stderr,"HIP runtime: %s\n",runtime);
#endif
    constexpr size_t blob=32768,capacity=129*blob;Resources r;
    size_t available=0,total=0;ck(hipMemGetInfo(&available,&total));if(available<capacity+(1536ull<<20))throw std::runtime_error("margin");
    ck(hipHostMalloc(&r.h,capacity,hipHostMallocMapped));ck(hipMalloc(&r.d,capacity));ck(hipStreamCreateWithFlags(&r.stream,hipStreamNonBlocking));
    std::vector<unsigned char> actual(capacity),expected(capacity);
    unsigned cases=0;
    for(int n:{0,1,2,3,8,32,128,129})for(int mode:{0,1,2})for(int failure:{0,1,2}){
        inject_failure=failure;unsigned before=batch_calls;
        std::vector<void*> dst(n);std::vector<const void*> src(n);std::vector<size_t> sizes(n,blob);
        for(int i=0;i<n;++i){std::memset(static_cast<unsigned char*>(r.h)+size_t(i)*blob,i+1,blob);std::memset(expected.data()+size_t(i)*blob,n-i,blob);dst[i]=static_cast<unsigned char*>(r.d)+size_t(i)*blob;src[i]=static_cast<unsigned char*>(r.h)+size_t(n-1-i)*blob;}
        ck(hipMemsetAsync(r.d,0,capacity,r.stream));
        ck(strata::core::copy_blobs(dst.data(),src.data(),sizes.data(),size_t(n),r.stream,mode));
        bool should_batch=mode!=0&&n>1&&n<=128;
        if(batch_calls-before!=unsigned(should_batch))throw std::runtime_error("dispatch mismatch");
        std::atomic<int> ready{0};ck(hipLaunchHostFunc(r.stream,[](void* p){static_cast<std::atomic<int>*>(p)->store(1);},&ready));
        ck(hipStreamSynchronize(r.stream));if(ready.load()!=1)throw std::runtime_error("callback ordering");
        if(n){ck(hipMemcpy(actual.data(),r.d,size_t(n)*blob,hipMemcpyDeviceToHost));if(std::memcmp(actual.data(),expected.data(),size_t(n)*blob))throw std::runtime_error("payload mismatch");}
        ++cases;
    }
    // Actual verifier entry point: contiguous destinations, independent sources.
    for(int n:{1,2,8,128,129}){
        inject_failure=0;std::vector<const uint8_t*> src(n);
        for(int i=0;i<n;++i){std::memset(static_cast<unsigned char*>(r.h)+size_t(i)*blob,i+1,blob);std::memset(expected.data()+size_t(i)*blob,n-i,blob);src[i]=static_cast<const uint8_t*>(r.h)+size_t(n-1-i)*blob;}
        ck(strata::core::copy_expert_blobs(static_cast<uint8_t*>(r.d),src.data(),n,blob,r.stream,1));ck(hipStreamSynchronize(r.stream));
        ck(hipMemcpy(actual.data(),r.d,size_t(n)*blob,hipMemcpyDeviceToHost));if(std::memcmp(actual.data(),expected.data(),size_t(n)*blob))throw std::runtime_error("verifier helper mismatch");++cases;
    }
    std::printf("{\"passed\":true,\"cases\":%u,\"batch_calls\":%u,\"partial_failure_fallback_verified\":true}\n",cases,batch_calls);
}catch(const std::exception& e){std::fprintf(stderr,"parity rejected: %s\n",e.what());return 1;}return 0;}
