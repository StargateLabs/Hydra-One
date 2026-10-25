// Software contracts only. No model assets, expert payloads or LLM execution.
#include "hydra/kernels/cpu/pool.hpp"
#include "hydra/kernels/cpu/expert_layout.hpp"
#include "hydra/platform/model_reader.hpp"
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace strata::kernels::cpu;
static void check(bool value,const char* why){if(!value)throw std::runtime_error(why);}
template<class F>static void rejects(F fn){bool refused=false;try{fn();}catch(const std::exception&){refused=true;}check(refused,"invalid component request accepted");}
int main(int argc,char**argv){try{
 ExpertPool pool(1,false,false);
 rejects([&]{pool.run(nullptr,-1);});rejects([&]{pool.run(nullptr,1);});
 ExpertJobMulti group{};group.nt=MAXT+1;
 rejects([&]{pool.run_split_multi(&group,1);});rejects([&]{pool.run_split_multi_native(NativeFmt{},&group,1);});
 pool.run(nullptr,0);
 uint8_t opaque=0;ActQ activation{};float output=0;ExpertJobMulti metadata{};
 metadata.blob=&opaque;metadata.nt=1;metadata.act[0]=&activation;metadata.out[0]=&output;
 check(valid_expert_group(metadata,false),"canonical activation contract");
 check(!valid_expert_group(metadata,true),"native activation missing");
 metadata.nact[0]=&opaque;check(valid_expert_group(metadata,true),"native activation contract");
 ExpertLayout layout;layout.n_layers=2;layout.n_expert=3;
 check(layout.blob_offset(1,2)==5*BLOB,"canonical offset");
 rejects([&]{layout.blob_offset(-1,0);});rejects([&]{layout.blob_offset(0,3);});
 layout.native=true;layout.offset={0,300};layout.bytes={100,200};
 check(layout.blob_offset(1,2)==700,"variable payload offset");
 layout.offset[1]=std::numeric_limits<uint64_t>::max()-1;rejects([&]{layout.blob_offset(1,2);});
 check(argc==2,"synthetic fixture path required");
 {std::ofstream f(argv[1],std::ios::binary);for(int i=0;i<8192;++i)f.put(char(i%127));}
 strata::platform::DirectFile file;std::string error;check(file.open(argv[1],error),"fixture open");
 check(!file.submit(0,nullptr,4096,0,error),"null I/O buffer accepted");
 void* buffer=strata::platform::DirectFile::alloc_aligned(4096);check(buffer,"allocation");
 check(!file.submit(0,buffer,4096,strata::platform::DirectFile::WAKE_TAG,error),"reserved tag accepted");
 file.close();strata::platform::DirectFile::free_aligned(buffer);
 strata::platform::ModelReader reader(argv[1],4096,1000);unsigned char bytes[32];reader.read_exact(17,bytes,sizeof bytes);
 for(int i=0;i<32;++i)check(bytes[i]==(i+17)%127,"synthetic byte mismatch");
 reader.cancel();rejects([&]{reader.read_exact(0,bytes,1);});
 std::cout<<"PASS pack offsets/overflow; pool batch rejection before kernels; synthetic IOCP ownership/cancellation; no model or GPU\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
