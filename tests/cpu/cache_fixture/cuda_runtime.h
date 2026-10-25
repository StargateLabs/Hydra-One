#pragma once
// TEST ONLY: CPU memory fixture, no CUDA/HIP DLL or device calls.
#include <cstdlib>
#include <cstring>
#include <cstddef>
using cudaError_t=int;using cudaStream_t=void*;
inline constexpr int cudaSuccess=0,cudaMemcpyHostToDevice=1,cudaMemcpyDeviceToHost=2;
inline size_t fixture_free=1024*1024,fixture_allocations=0;
inline bool fixture_copy_error=false;
inline bool fixture_free_error=false;
inline bool fixture_memory_unknown=false;
inline int cudaMemGetInfo(size_t* f,size_t* t){if(fixture_memory_unknown)return 1;*f=fixture_free;*t=1024*1024;return 0;}
inline int cudaMalloc(void** p,size_t n){*p=std::malloc(n);if(*p)++fixture_allocations;return *p?0:1;}
inline int cudaFree(void* p){if(fixture_free_error)return 1;if(p){std::free(p);--fixture_allocations;}return 0;}
inline int cudaMemset(void* p,int value,size_t n){std::memset(p,value,n);return 0;}
inline int cudaMemcpy(void* d,const void* s,size_t n,int){if(fixture_copy_error)return 1;std::memcpy(d,s,n);return 0;}
inline int cudaMemcpyAsync(void* d,const void* s,size_t n,int type,cudaStream_t){return cudaMemcpy(d,s,n,type);}
inline int cudaStreamSynchronize(cudaStream_t){return fixture_copy_error?1:0;}
inline int cudaDeviceSynchronize(){return fixture_copy_error?1:0;}
inline const char* cudaGetErrorString(int){return "CPU fixture injected failure";}
inline int cudaGetLastError(){return 1;}
