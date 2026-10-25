#pragma once
// Child allocation accounting inside the existing HYDRA process reservation.
// No runtime/GPU admission is granted here. Ordinary processes pass through.
#if !defined(STRATA_BUDGET_RUNTIME_TYPES_PROVIDED)
#include <cuda_runtime.h>
#endif
#include <array>
#include <cstdlib>
#include <cstdint>
#include <limits>
#include <list>
#include <iterator>
#include <mutex>
#include <new>

namespace strata::core {
enum class BudgetComponent : unsigned { Weights, ExpertCache, SequenceState, KVCache,
                                        Workspace, Staging, RuntimeBuffers, SafetyMargin };
#if !defined(CUDART_VERSION) && !defined(STRATA_USE_HIP)
// Preserve the existing CPU-only CUDA facade without requiring GPU symbols.
// This branch provides no native GPU budget capability.
struct BudgetAllocator {
    BudgetComponent component;
    template<class T> cudaError_t device_alloc(T** p,size_t bytes)const {
        return cudaMalloc(reinterpret_cast<void**>(p),bytes);
    }
};
inline BudgetAllocator budget_for(BudgetComponent component){return {component};}
inline cudaError_t budget_device_free(void* p){return cudaFree(p);}
#else
namespace budget_detail {
inline cudaError_t invalid() {
#if defined(STRATA_USE_HIP)
    return hipErrorInvalidValue;
#else
    return cudaErrorInvalidValue;
#endif
}
inline cudaError_t exhausted() {
#if defined(STRATA_USE_HIP)
    return hipErrorOutOfMemory;
#else
    return cudaErrorMemoryAllocation;
#endif
}
enum class Kind { Device, Host, Registered, ExternalHost };
struct Entry { void* pointer; uint64_t bytes; unsigned index; int device; Kind kind;
               bool releasing=false; uint64_t charged=0; void* parent=nullptr; };
struct Ledger {
    std::mutex mutex;
    std::array<uint64_t,16> limits{}, used{};
    std::list<Entry> allocations;
    bool managed=false, valid=false;
    Ledger() {
        managed=std::getenv("HYDRA_ADMISSION_LEASE_FILE")!=nullptr;
        if(!managed)return;
        const char* owner=std::getenv("HYDRA_MEMORY_OWNER");
        const char* p=std::getenv("HYDRA_NATIVE_MEMORY_ENVELOPE");
        if(!owner||!*owner||!p)return;
        // Fixed order matches hydra_memory_budget.COMPONENTS: RAM then VRAM.
        for(unsigned i=0;i<16;++i) {
            uint64_t n=0;
            if(*p<'0'||*p>'9')return;
            while(*p>='0'&&*p<='9') {
                unsigned digit=unsigned(*p++-'0');
                if(n>(uint64_t(INT64_MAX)-digit)/10)return;
                n=n*10+digit;
            }
            limits[i]=n;
            if(i<15) {if(*p++!=';')return;}
            else if(*p)return;
        }
        for(unsigned start: {0u,8u}) {
            uint64_t sum=0;
            for(unsigned i=start;i<start+8;++i) {
                if(limits[i]>uint64_t(INT64_MAX)-sum)return;
                sum+=limits[i];
            }
        }
        valid=true;
    }
};
inline Ledger& ledger(){static Ledger instance;return instance;}
inline cudaError_t allocate(void** pointer,size_t bytes,unsigned component,Kind kind,unsigned flags) {
    auto& l=ledger();
    void* allocated=nullptr;
    auto raw=[&]() {
        void** destination=l.managed?&allocated:pointer;
        if(kind==Kind::Device)return cudaMalloc(destination,bytes);
        if(kind==Kind::Registered)return cudaHostRegister(*pointer,bytes,flags);
#if defined(STRATA_USE_HIP)
        return hipHostMalloc(destination,bytes,flags);
#else
        return cudaHostAlloc(destination,bytes,flags);
#endif
    };
    if(!l.managed)return raw();
    if(!pointer||!bytes||bytes>uint64_t(INT64_MAX)||component>=8||!l.valid)return invalid();
    std::unique_lock<std::mutex> lock(l.mutex);
    unsigned index=component+(kind==Kind::Device?8:0);
    uint64_t charge=bytes;void* parent=nullptr;
    if(kind==Kind::Registered) {
        if(!*pointer)return invalid();
        const auto first=reinterpret_cast<uintptr_t>(*pointer);
        if(bytes>(std::numeric_limits<uintptr_t>::max)()-first)return invalid();
        for(const auto& e:l.allocations)if(e.kind!=Kind::Device) {
            const auto other=reinterpret_cast<uintptr_t>(e.pointer);
            if(e.bytes>(std::numeric_limits<uintptr_t>::max)()-other)return invalid();
            if(first<other+e.bytes&&other<first+bytes) {
                if(e.kind==Kind::ExternalHost&&!e.releasing&&first>=other&&first+bytes<=other+e.bytes) {
                    parent=e.pointer;charge=0; // A pin of owned RAM is not another RAM allocation.
                } else return invalid();
            }
        }
    }
    if(l.used[index]>l.limits[index]||charge>l.limits[index]-l.used[index])return exhausted();
    int device=-1;
    auto status=cudaGetDevice(&device);
    if(status!=cudaSuccess)return status;
    // Allocate ledger metadata BEFORE calling the driver; no metadata allocation
    // is needed after it succeeds. Keep the mutex over reservation and commit.
    try{l.allocations.push_back({nullptr,uint64_t(bytes),index,device,kind});}
    catch(const std::bad_alloc&){return exhausted();}
    auto entry=std::prev(l.allocations.end());entry->charged=charge;entry->parent=parent;l.used[index]+=charge;
    status=raw();
    if(status!=cudaSuccess) {
        if(kind==Kind::Registered||allocated) {
            // Failed registration/allocation may leave ownership uncertain.
            // Retain the reservation until whole-process cleanup attests it.
            entry->pointer=kind==Kind::Registered?*pointer:allocated;
            entry->releasing=true; // uncertain acquisition is quarantined, never retried as a normal free
            return status;
        }
        l.used[index]-=charge;l.allocations.erase(entry);return status;
    }
    if(kind!=Kind::Registered)*pointer=allocated;
    entry->pointer=*pointer;
    return status;
}
inline cudaError_t release(void* pointer,Kind kind) {
    auto& l=ledger();
    auto raw=[&]() {
        if(kind==Kind::Device)return cudaFree(pointer);
        if(kind==Kind::Registered)return cudaHostUnregister(pointer);
        return cudaFreeHost(pointer);
    };
    if(!l.managed)return raw();
    if(!pointer)return cudaSuccess;
    std::unique_lock<std::mutex> lock(l.mutex);
    for(auto it=l.allocations.begin();it!=l.allocations.end();++it) {
        if(it->pointer!=pointer||it->kind!=kind)continue;
        if(it->releasing)return invalid();
        int device=-1;auto status=cudaGetDevice(&device);
        if(status!=cudaSuccess)return status;
        if(device!=it->device)return invalid();
        // No recycle when the driver cannot attest completion. Keep both the
        // pointer record and its charge on synchronization/free failure.
        it->releasing=true;
        lock.unlock();
        status=cudaDeviceSynchronize();
        if(status==cudaSuccess)status=raw();
        lock.lock();
        if(status!=cudaSuccess)return status; // Quarantine an uncertain release; no second free.
        l.used[it->index]-=it->charged;l.allocations.erase(it);return cudaSuccess;
    }
    return invalid(); // Unknown owner/alias: do not free somebody else's buffer.
}
} // namespace budget_detail

// Actual OS-backed allocations share the SAME child ledger. Driver registration
// borrows them; a mapping cannot be released while a registration still exists.
template<class Allocate>
inline void* budget_host_mapping_alloc(size_t bytes,BudgetComponent component,Allocate allocate) {
    auto& l=budget_detail::ledger();
    if(!l.managed)return allocate();
    const auto index=unsigned(component);
    if(!l.valid||!bytes||bytes>uint64_t(INT64_MAX)||index>=8)return nullptr;
    std::unique_lock<std::mutex> lock(l.mutex);
    if(l.used[index]>l.limits[index]||bytes>l.limits[index]-l.used[index])return nullptr;
    try{l.allocations.push_back({nullptr,uint64_t(bytes),index,-1,budget_detail::Kind::ExternalHost});}
    catch(const std::bad_alloc&){return nullptr;}
    auto entry=std::prev(l.allocations.end());entry->charged=bytes;l.used[index]+=bytes;
    void* pointer=nullptr;
    try{pointer=allocate();}
    catch(...){entry->releasing=true;throw;} // Unknown allocator outcome retains its charge.
    if(!pointer){l.used[index]-=bytes;l.allocations.erase(entry);return nullptr;}
    entry->pointer=pointer;return pointer;
}
template<class Release>
inline bool budget_host_mapping_free(void* pointer,Release release) {
    auto& l=budget_detail::ledger();
    if(!l.managed)return release();
    if(!pointer)return true;
    std::unique_lock<std::mutex> lock(l.mutex);
    for(auto it=l.allocations.begin();it!=l.allocations.end();++it) {
        if(it->pointer!=pointer||it->kind!=budget_detail::Kind::ExternalHost)continue;
        if(it->releasing)return false;
        for(const auto& child:l.allocations)if(child.parent==pointer)return false;
        it->releasing=true;lock.unlock();bool released=false;
        try{released=release();}
        catch(...){lock.lock();throw;} // Unknown outcome remains quarantined.
        lock.lock();
        if(!released)return false;
        l.used[it->index]-=it->charged;l.allocations.erase(it);return true;
    }
    return false;
}
struct BudgetAllocator {
    BudgetComponent component;
    template<class T> cudaError_t device_alloc(T** p,size_t bytes)const {
        return budget_detail::allocate(reinterpret_cast<void**>(p),bytes,unsigned(component),budget_detail::Kind::Device,0);
    }
    template<class T> cudaError_t host_alloc(T** p,size_t bytes,unsigned flags)const {
        return budget_detail::allocate(reinterpret_cast<void**>(p),bytes,unsigned(component),budget_detail::Kind::Host,flags);
    }
    template<class T> cudaError_t malloc_host(T** p,size_t bytes)const {
#if defined(STRATA_USE_HIP)
        return host_alloc(p,bytes,hipHostMallocDefault);
#else
        return host_alloc(p,bytes,cudaHostAllocDefault);
#endif
    }
    cudaError_t host_register(void* p,size_t bytes,unsigned flags)const {
        return budget_detail::allocate(&p,bytes,unsigned(component),budget_detail::Kind::Registered,flags);
    }
};
inline BudgetAllocator budget_for(BudgetComponent component){return {component};}
inline cudaError_t budget_device_free(void* p){return budget_detail::release(p,budget_detail::Kind::Device);}
inline cudaError_t budget_host_free(void* p){return budget_detail::release(p,budget_detail::Kind::Host);}
inline cudaError_t budget_host_unregister(void* p){return budget_detail::release(p,budget_detail::Kind::Registered);}
#endif
} // namespace strata::core
