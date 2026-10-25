#pragma once
// Host ownership only. Backend completion must be supplied by the real caller.
#include <cstdint>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <vector>

namespace strata::core {
class SlotLifecycle {
public:
 enum class State { Reserved, Loading, Resident, EvictionPending, Failed, Released };
 struct Slot { State state=State::Reserved; uint64_t generation=1; uint32_t pins=0,inflight=0; };
 struct Storage { std::mutex mutex; std::vector<Slot> slots; bool closed=false; };
 class Lease {
  std::shared_ptr<Storage> owner_; size_t slot_=0; uint64_t generation_=0;
  bool running_=false;
  friend class SlotLifecycle;
  Lease(std::shared_ptr<Storage> owner,size_t slot,uint64_t generation):owner_(std::move(owner)),slot_(slot),generation_(generation){}
 public:
  Lease()=default; Lease(const Lease&)=delete; Lease& operator=(const Lease&)=delete;
  Lease(Lease&& other) noexcept { *this=std::move(other); }
  Lease& operator=(Lease&& other) noexcept { if(this!=&other){reset();owner_=std::move(other.owner_);slot_=other.slot_;generation_=other.generation_;running_=other.running_;other.running_=false;}return *this; }
  ~Lease(){reset();}
  // Teardown could not attest completion. Keep the pin in Storage permanently;
  // dropping this host object must not make the device address recyclable.
  // Whole-process cleanup is the only remaining release boundary.
  void quarantine() noexcept {owner_.reset();}
  void reset(){if(running_){quarantine();return;}if(owner_){auto keep=std::move(owner_);std::lock_guard<std::mutex> lock(keep->mutex);auto& s=keep->slots[slot_];if(s.pins)--s.pins;}}
  bool begin_operation(){if(!owner_||running_)return false;std::lock_guard<std::mutex> lock(owner_->mutex);auto& s=owner_->slots[slot_];if(owner_->closed||s.generation!=generation_||(s.state!=State::Loading&&s.state!=State::Resident)||s.inflight==UINT32_MAX)return false;++s.inflight;running_=true;return true;}
  // Caller must first attest the event/stream covering its actual submitted work.
  bool complete_operation(){if(!running_)return true;if(!owner_)return false;std::lock_guard<std::mutex> lock(owner_->mutex);auto& s=owner_->slots[slot_];if(owner_->closed||s.generation!=generation_||!s.inflight)return false;--s.inflight;running_=false;return true;}
  bool valid()const {if(!owner_)return false;std::lock_guard<std::mutex> lock(owner_->mutex);const auto& s=owner_->slots[slot_];return !owner_->closed&&s.generation==generation_&&(s.state==State::Loading||s.state==State::Resident||s.state==State::EvictionPending);}
  uint64_t generation()const{return generation_;}
  size_t slot()const{return slot_;}
 };
 SlotLifecycle():storage_(std::make_shared<Storage>()){}
 SlotLifecycle(const SlotLifecycle&)=delete;
 SlotLifecycle& operator=(const SlotLifecycle&)=delete;
 bool owns(const Lease& lease)const {return lease.owner_==storage_;}
 // Reserve the complete graph's referenced set before its first submission.
 // A partial failure has submitted no work, so only those new reservations roll back.
 static bool begin_operations(std::vector<Lease>& leases){
  size_t count=0;
  for(auto& lease:leases){
   if(!lease.begin_operation()){
    for(size_t i=0;i<count;++i)if(!leases[i].complete_operation())leases[i].quarantine();
    return false;
   }
   ++count;
  }
  return true;
 }
 // Only a caller that observed completion of every covered stream may invoke this.
 static bool complete_operations(std::vector<Lease>& leases){
  for(auto& lease:leases)if(!lease.complete_operation()){
   for(auto& retained:leases)retained.quarantine();
   return false;
  }
  return true;
 }
 bool reset(size_t count){if(!close())return false;storage_=std::make_shared<Storage>();storage_->slots.resize(count);return true;}
 bool begin_load(size_t index){std::lock_guard<std::mutex> lock(storage_->mutex);if(storage_->closed||index>=storage_->slots.size())return false;auto& s=storage_->slots[index];if(s.pins||s.inflight||s.state!=State::Reserved||s.generation==UINT64_MAX)return false;++s.generation;s.state=State::Loading;s.inflight=1;return true;}
 // Only a fully leased consumer may use this transition. No pin, copy or kernel
 // can remain; revocation and the new generation precede every overwrite.
 bool begin_replace(size_t index){std::lock_guard<std::mutex> lock(storage_->mutex);if(storage_->closed||index>=storage_->slots.size())return false;auto& s=storage_->slots[index];if(s.state!=State::Resident||s.pins||s.inflight||s.generation==UINT64_MAX)return false;++s.generation;s.state=State::Loading;s.inflight=1;return true;}
 bool complete(size_t index,bool success){std::lock_guard<std::mutex> lock(storage_->mutex);if(storage_->closed||index>=storage_->slots.size())return false;auto& s=storage_->slots[index];if(!s.inflight||s.state!=State::Loading)return false;--s.inflight;s.state=success?State::Resident:State::Failed;if(!success&&s.generation!=UINT64_MAX)++s.generation;return true;}
 Lease pin(size_t index,bool same_stream_ordered=false){std::lock_guard<std::mutex> lock(storage_->mutex);if(storage_->closed||index>=storage_->slots.size())return {};auto& s=storage_->slots[index];if((s.state!=State::Resident&&!(same_stream_ordered&&s.state==State::Loading))||s.pins==UINT32_MAX)return {};++s.pins;return Lease(storage_,index,s.generation);}
 bool evict(size_t index,bool backend_completed){std::lock_guard<std::mutex> lock(storage_->mutex);if(storage_->closed||index>=storage_->slots.size())return false;auto& s=storage_->slots[index];if(s.state!=State::Resident&&s.state!=State::EvictionPending)return false;s.state=State::EvictionPending;if(!backend_completed||s.pins||s.inflight||s.generation==UINT64_MAX)return false;++s.generation;s.state=State::Released;return true;}
 bool close(){std::lock_guard<std::mutex> lock(storage_->mutex);if(storage_->closed)return true;for(const auto& s:storage_->slots)if(s.pins||s.inflight)return false;storage_->closed=true;for(auto& s:storage_->slots){if(s.generation!=UINT64_MAX)++s.generation;s.state=State::Released;}return true;}
 Slot snapshot(size_t index)const{std::lock_guard<std::mutex> lock(storage_->mutex);if(index>=storage_->slots.size())throw std::out_of_range("slot");return storage_->slots[index];}
private:std::shared_ptr<Storage> storage_;
};
} // namespace strata::core
