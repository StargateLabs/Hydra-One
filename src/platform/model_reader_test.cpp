#include "hydra/platform/model_reader.hpp"
#include <fstream>
#include <iostream>
#include <vector>
#include <cstring>
#include <stdexcept>
using strata::platform::ModelReader;
void check(bool x,const char* m){if(!x)throw std::runtime_error(m);}
template<class F> void rejects(F fn){bool rejected=false;try{fn();}catch(const std::exception&){rejected=true;}check(rejected,"expected rejection");}
int main(int argc,char**argv){try{
 check(argc==2,"fixture path required");std::string path=argv[1];std::vector<unsigned char> expected(3*4096+731);
 for(size_t i=0;i<expected.size();++i)expected[i]=(i*131+17)%251;
 {std::ofstream f(path,std::ios::binary);f.write((char*)expected.data(),expected.size());}
 rejects([&]{ModelReader bad(path,4097,2000);});rejects([&]{ModelReader bad(path+".missing",4096,2000);});
 for(int cycle=0;cycle<3;++cycle){ModelReader r(path,4096,2000);std::vector<unsigned char> actual(expected.size());
 r.read_exact(0,actual.data(),actual.size());check(actual==expected,"full content mismatch");
 std::memset(actual.data(),0,actual.size());r.read_exact(17,actual.data(),expected.size()-17);
 check(std::memcmp(actual.data(),expected.data()+17,expected.size()-17)==0,"unaligned tail mismatch");
 rejects([&]{r.read_exact(expected.size()-2,actual.data(),3);});
 rejects([&]{r.read_exact(UINT64_MAX-2,actual.data(),8);});
 r.cancel();rejects([&]{r.read_exact(0,actual.data(),1);});}
 // Actual queued OVERLAPPED requests must drain before their shared buffer is freed.
 strata::platform::DirectFile file;std::string error;check(file.open(path,error),"open drain fixture");
 void* buffer=strata::platform::DirectFile::alloc_aligned(4096*16);check(buffer,"drain buffer");
 for(int i=0;i<16;++i)check(file.submit(0,(char*)buffer+i*4096,4096,i,error),"queued drain read");
 file.close();strata::platform::DirectFile::free_aligned(buffer);check(file.open(path,error),"reopen after drain");
 strata::platform::Completion completion;check(file.wait(&completion,1,0)==0,"stale completion after reopen");file.close();
 std::cout<<"PASS exact consumer bytes; unaligned offsets/tail; short/overflow/missing/parameter errors; cancellation;16 pending reads drained; repeated close/reopen\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
