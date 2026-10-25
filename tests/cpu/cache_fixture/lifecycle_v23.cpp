#include "hydra/core/slot_lifecycle.hpp"
#include <iostream>
#include <stdexcept>
#include <type_traits>
static_assert(!std::is_copy_constructible_v<strata::core::SlotLifecycle>,"slot ownership must not be copied");
using strata::core::SlotLifecycle;
void check(bool v,const char* s){if(!v)throw std::runtime_error(s);}
int main(){try{
 SlotLifecycle slots;check(slots.reset(2),"reset");check(slots.begin_load(0),"load");check(!slots.pin(0).valid(),"loading exposed");check(!slots.close(),"inflight freed");check(slots.complete(0,true),"complete");
 auto a=slots.pin(0);check(a.valid(),"pin");auto generation=a.generation();check(!slots.begin_load(0),"pinned overwrite");check(!slots.evict(0,true),"pinned eviction");check(!slots.close(),"pinned close");a.reset();
 check(!slots.evict(0,false),"unverified completion evicted");check(slots.evict(0,true),"completed eviction");check(!slots.pin(0).valid(),"released reference");check(slots.reset(2),"reopen");check(slots.begin_load(1)&&slots.complete(1,false),"copy failure");check(!slots.pin(1).valid()&&!slots.begin_load(1),"failed slot reused");check(slots.close(),"close failed payload");
 (void)generation;std::cout<<"PASS v23 slot ownership/generation/inflight/pending eviction/failure/close; CPU metadata only\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
