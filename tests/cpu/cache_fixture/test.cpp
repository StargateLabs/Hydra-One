#include <cuda_runtime.h>
#include "hydra/core/expert_cache.hpp"
#include <stdexcept>
#include <iostream>
#include <filesystem>
#include <fstream>
#include <cstdlib>
void check(bool x,const char* m){if(!x)throw std::runtime_error(m);}
int main(){try{
 const auto profile=(std::filesystem::path(std::getenv("TEMP")?std::getenv("TEMP"):".")/"v19-expert-profile.bin").string();
 std::string profile_error;std::vector<std::pair<int32_t,int32_t>> ranked{{0,0},{0,1}},loaded;int64_t slots=-1;
 check(strata::core::write_expert_profile(profile,1,3,ranked,profile_error),"write valid profile");
 check(strata::core::read_expert_profile(profile,1,3,loaded,slots,profile_error)&&loaded==ranked&&slots==2,"valid profile roundtrip");
 {std::fstream f(profile,std::ios::binary|std::ios::in|std::ios::out);uint32_t version=2;f.seekp(4);f.write(reinterpret_cast<char*>(&version),4);}
 check(!strata::core::read_expert_profile(profile,1,3,loaded,slots,profile_error),"unknown profile version accepted");
 check(!strata::core::write_expert_profile(profile,1,3,{{0,0},{0,0}},profile_error),"duplicate profile written");
 check(strata::core::write_expert_profile(profile,1,3,ranked,profile_error),"rewrite valid profile");
 {std::fstream f(profile,std::ios::binary|std::ios::in|std::ios::out);uint16_t duplicate[2]={0,0};f.seekp(28);f.write(reinterpret_cast<char*>(duplicate),4);}
 check(!strata::core::read_expert_profile(profile,1,3,loaded,slots,profile_error),"duplicate profile admitted");
 check(loaded==ranked&&slots==2,"invalid profile mutated published residency");
 check(strata::core::write_expert_profile(profile,1,3,ranked,profile_error),"rewrite before oversized header");
 {std::fstream f(profile,std::ios::binary|std::ios::in|std::ios::out);uint32_t oversized=UINT32_MAX;f.seekp(16);f.write(reinterpret_cast<char*>(&oversized),4);f.write(reinterpret_cast<char*>(&oversized),4);}
 check(!strata::core::read_expert_profile(profile,1,3,loaded,slots,profile_error),"oversized profile header admitted");
 check(strata::core::write_expert_profile(profile,1,3,ranked,profile_error),"rewrite before truncation");
 std::filesystem::resize_file(profile,25);
 check(!strata::core::read_expert_profile(profile,1,3,loaded,slots,profile_error),"truncated profile admitted");
 std::filesystem::remove(profile);
 strata::core::ExpertCache cache;std::string error;uint8_t a[16],b[16];std::memset(a,17,16);std::memset(b,31,16);
 fixture_memory_unknown=true;check(!cache.open(1,1,3,8,error)&&fixture_allocations==0,"unknown VRAM admitted allocation");fixture_memory_unknown=false;
 check(cache.open_sized({8,16},1,3,error),"open sized");
 check(cache.slot_of(0,0)==-1,"initial miss");int slot=cache.admit(0,0);check(slot==0&&cache.slot_of(0,0)==0,"identity hit");
 check(cache.fill_slot(slot,a,nullptr,error,8)&&cache.verify_slot(slot,a,error,8),"actual bytes");
 check(!cache.fill_slot(slot,b,nullptr,error,16),"oversized payload accepted despite slot padding");
 check(cache.verify_slot(slot,a,error,8),"rejected write changed bytes");
 check(!cache.fill_slot_blocking(slot,b,error,8)&&cache.verify_slot(slot,a,error,8),"resident raw-reference slot overwritten without revocation");
 {auto lease=cache.acquire(slot,error);check(lease.valid(),"v23 actual cache pin");
  check(!cache.fill_slot_blocking(slot,b,error,8),"v23 pinned overwrite accepted");
  cache.close();check(cache.valid()&&!cache.close_error().empty(),"v23 close freed a pinned arena");
  check(lease.valid(),"v23 refused close invalidated live reference");}
 check(!cache.request_eviction(slot,error)&&error=="REVOCABLE_GRAPH_SLOT_REFERENCES_REQUIRED","v23 raw graph eviction enabled");
 check(!cache.fill_slot_blocking(slot,b,error,-1),"negative size accepted");
 check(!cache.fill_slot_queued(slot,b,error,9),"queued oversized write accepted");
 check(!cache.verify_slot(slot,a,error,9),"oversized verify accepted");
 check(cache.admit(0,1)==1&&cache.admit(0,2)==-1,"budget no eviction");
 fixture_copy_error=true;check(!cache.fill_slot_blocking(1,b,error,16),"copy error swallowed");fixture_copy_error=false;
 cache.close();check(fixture_allocations==0&&!cache.valid()&&cache.slot_of(0,0)==-1,"close invalidation/leak");
 uint8_t large[512];std::memset(large,87,sizeof(large));
 check(cache.open_sized({8,512},1,3,error),"open cross-slot fixture");
 check(cache.fill_slot_blocking(1,large,error,512),"seed neighbor");
 check(!cache.fill_slot_blocking(0,large,error,512)&&cache.verify_slot(1,large,error,512),"cross-slot corruption not prevented");cache.close();
 check(!cache.open_sized({-1,8},1,3,error),"negative payload allocated");
 check(cache.open(1,1,3,8,error)&&cache.slot_of(0,0)==-1,"new request contamination");
 int ordered_slot=cache.admit(0,0);void* stream=reinterpret_cast<void*>(1);
 check(cache.fill_slot(ordered_slot,a,stream,error,8),"ordered fill");
 check(!cache.acquire_ordered(ordered_slot,nullptr,error).valid(),"cross-stream lease without fence");
 {auto lease=cache.acquire_ordered(ordered_slot,stream,error);check(lease.valid(),"same-stream ordered pin");
  check(cache.complete_ordered(ordered_slot,stream,error),"backend completion certificate");
  check(lease.valid(),"completion invalidated lease");}
 cache.close();
 check(cache.open(1,1,3,8,error),"v24 release fixture");fixture_free_error=true;cache.close();
 check(cache.valid()&&fixture_allocations==1&&!cache.close_error().empty(),"v24 failed free falsely released arena");
 fixture_free_error=false;cache.close();check(!cache.valid()&&fixture_allocations==0,"v24 explicit cleanup");
 fixture_free=0;check(!cache.open(1,1,3,8,error)&&fixture_allocations==0,"insufficient budget allocated");
 std::cout<<"PASS actual ExpertCache source using CPU memory fixture: key/hit/miss/bytes/slot bounds/copy error/budget/close/reopen; GPU and native inference NOT_EXECUTED; no automatic eviction policy\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
