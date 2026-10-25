#pragma once
// Exact consumer reads through the existing DirectFile IOCP implementation.
#include "hydra/platform/direct_file.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <mutex>
namespace strata::platform {
class ModelReader {
    std::mutex read_mu_;
    DirectFile file_; void* bounce_=nullptr; uint32_t chunk_; int timeout_;
    std::atomic<bool> cancelled_{false}; uint64_t reads_=0,consumer_=0,physical_=0;
public:
    ModelReader(const std::string& path,uint32_t chunk=1024*1024,int timeout=30000):chunk_(chunk),timeout_(timeout){
        if(chunk<4096||chunk>8*1024*1024||chunk%4096||timeout<1||timeout>30000)throw std::runtime_error("IOCP invalid chunk/alignment/timeout");
        std::string error;if(!file_.open(path,error))throw std::runtime_error(error);
        bounce_=DirectFile::alloc_aligned(chunk_);if(!bounce_)throw std::runtime_error("IOCP aligned allocation failed");
    }
    ~ModelReader(){std::lock_guard<std::mutex> lock(read_mu_);file_.close();DirectFile::free_aligned(bounce_);std::fprintf(stderr,"HYDRA_IOCP consumer_bytes=%llu physical_bytes=%llu completions=%llu cleanup=closed\n",(unsigned long long)consumer_,(unsigned long long)physical_,(unsigned long long)reads_);}
    // Cancellation never closes a handle concurrently with its read/wait owner.
    void cancel(){cancelled_.store(true,std::memory_order_release);std::unique_lock<std::mutex> lock(read_mu_,std::try_to_lock);if(lock.owns_lock())file_.close();}
    void read_exact(uint64_t offset,void* destination,size_t bytes){
        std::unique_lock<std::mutex> lock(read_mu_,std::try_to_lock);
        if(!lock.owns_lock())throw std::runtime_error("IOCP reader busy");
        if(cancelled_)file_.close();
        if(cancelled_||!file_.is_open())throw std::runtime_error("IOCP cancelled/closed");
        if((bytes&&!destination)||offset>file_.size()||bytes>file_.size()-offset)throw std::runtime_error("IOCP short read/range overflow");
        auto out=static_cast<unsigned char*>(destination);
        try { while(bytes){
            uint64_t aligned=offset-offset%4096;uint32_t skip=uint32_t(offset-aligned);
            uint32_t count=uint32_t(std::min<uint64_t>(bytes,chunk_-skip));
            uint32_t length=((skip+count+4095)/4096)*4096;
            std::string error;if(!file_.submit(aligned,bounce_,length,reads_,error))throw std::runtime_error(error);
            Completion c;auto deadline=std::chrono::steady_clock::now()+std::chrono::milliseconds(timeout_);
            for(;;){
                int n=file_.wait(&c,1,50);
                if(n&&c.tag!=DirectFile::WAKE_TAG)break;
                if(cancelled_||std::chrono::steady_clock::now()>=deadline){throw std::runtime_error("IOCP cancelled/deadline; drained");}
            }
            if(cancelled_)throw std::runtime_error("IOCP cancelled before consumer copy");
            uint64_t expected=std::min<uint64_t>(length,file_.size()-aligned);
            if(!c.ok||c.tag!=reads_||c.bytes!=expected||c.bytes<skip+count)throw std::runtime_error("IOCP incomplete/error completion; no fallback");
            std::memcpy(out,static_cast<unsigned char*>(bounce_)+skip,count);
            ++reads_;physical_+=c.bytes;consumer_+=count;out+=count;offset+=count;bytes-=count;
        }} catch(...) { cancelled_=true;file_.close();throw; }
    }
};
}
