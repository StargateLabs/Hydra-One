#pragma once
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>

// Synchronous ownership: every callback completes before run() returns or throws.
// Separate invocation lock permits multiple callers without mixing their buffers.
class PersistentFillWorkers {
    std::mutex invocation_, mutex_;
    std::condition_variable ready_, finished_;
    std::vector<std::thread> workers_;
    std::function<void(size_t)> work_;
    std::atomic<size_t> next_{0};
    size_t count_=0, active_=0, remaining_=0, generation_=0;
    bool stopping_=false;
    std::exception_ptr error_;
    void consume() noexcept {
        for(size_t i;(i=next_.fetch_add(1,std::memory_order_relaxed))<count_;) {
            try { work_(i); }
            catch(...) { std::lock_guard<std::mutex> lock(mutex_);if(!error_)error_=std::current_exception(); }
        }
    }
    void worker(size_t id) noexcept {
        size_t seen=0;
        for(;;) {
            std::unique_lock<std::mutex> lock(mutex_);
            ready_.wait(lock,[&]{return stopping_||generation_!=seen;});
            if(stopping_)return;
            seen=generation_;
            if(id>=active_)continue;
            lock.unlock();consume();lock.lock();
            if(--remaining_==0)finished_.notify_one();
        }
    }
    void stop() noexcept {
        {std::lock_guard<std::mutex> lock(mutex_);stopping_=true;}
        ready_.notify_all();for(auto& thread:workers_)if(thread.joinable())thread.join();
    }
public:
    explicit PersistentFillWorkers(size_t threads) {
        try {for(size_t i=0;i+1<std::max<size_t>(1,threads);++i)workers_.emplace_back([this,i]{worker(i);});}
        catch(...) {stop();throw;}
    }
    ~PersistentFillWorkers(){std::lock_guard<std::mutex> serialized(invocation_);stop();}
    PersistentFillWorkers(const PersistentFillWorkers&)=delete;
    PersistentFillWorkers& operator=(const PersistentFillWorkers&)=delete;
    void run(size_t count,size_t threads,const std::function<void(size_t)>& work) {
        std::lock_guard<std::mutex> serialized(invocation_);
        if(!count)return;
        if(count==1||threads<=1||workers_.empty()){for(size_t i=0;i<count;++i)work(i);return;}
        {
            std::lock_guard<std::mutex> lock(mutex_);
            work_=work;count_=count;next_.store(0,std::memory_order_relaxed);error_=nullptr;
            active_=std::min({workers_.size(),count-1,threads-1});remaining_=active_;++generation_;
        }
        ready_.notify_all();consume();
        std::unique_lock<std::mutex> lock(mutex_);finished_.wait(lock,[&]{return remaining_==0;});
        auto error=error_;work_=nullptr;lock.unlock();if(error)std::rethrow_exception(error);
    }
};
