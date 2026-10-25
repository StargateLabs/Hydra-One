// Bounded CPU acceptance over ONE real expert admitted by the v18 source-byte manifest.
// This is not a language-model, draft/target, GPU or full native-engine inference test.
#include "hydra/kernels/cpu/portable_expert.hpp"
#include "hydra/kernels/cpu/expert_layout.hpp"
#include "hydra/kernels/cpu/pool.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <cstdio>
#include <stdexcept>
#include <vector>
#ifdef _WIN32
#include "hydra/platform/model_reader.hpp"
#endif
namespace c=strata::kernels::cpu;
static void require(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
static double fp16(const uint8_t* p){
 uint16_t bits;std::memcpy(&bits,p,2);unsigned exp=(bits>>10)&31,m=bits&1023;
 double value=exp==0?std::ldexp(double(m),-24):exp==31?NAN:std::ldexp(double(1024+m),int(exp)-25);
 return bits&0x8000?-value:value;
}
// Independent double reference visits each weight individually, unlike the
// production block/chunk integer-reduction kernel. Shares only format constants.
static double reference_dot(const uint8_t* codes,const uint8_t* scales,const c::ActQ& a,int n){
 double sum=0;
 for(int col=0;col<n;++col){
  int value=int((codes[col/4]>>(2*(col%4)))&3)-1;
  sum+=double(value)*fp16(scales+2*(col/c::QK))*double(a.q[col])*double(a.scale[col/c::QKA]);
 }
 return sum;
}
static double check(const float* actual,const std::vector<double>& expected){
 double max_error=0;
 for(size_t i=0;i<expected.size();++i){
  require(std::isfinite(actual[i])&&std::isfinite(expected[i]),"nonfinite output");
  double error=std::fabs(double(actual[i])-expected[i]);max_error=std::max(max_error,error);
  require(error<=1e-4+1e-4*std::fabs(expected[i]),"real-weight numerical mismatch");
 }
 return max_error;
}
int main(int argc,char** argv){try{
 require(argc==2||argc==3,"one admitted expert slice path and optional --iocp required");
 const bool iocp=argc==3;
 require(!iocp||std::strcmp(argv[2],"--iocp")==0,"unknown reader mode");
 std::ifstream file(argv[1],std::ios::binary|std::ios::ate);require(bool(file),"missing expert slice");
 require(file.tellg()==std::streamoff(c::BLOB),"wrong expert slice size");file.seekg(0);
 std::vector<uint8_t> blob(c::BLOB);file.read(reinterpret_cast<char*>(blob.data()),blob.size());require(bool(file),"short expert slice read");
 if(iocp){
#ifdef _WIN32
  std::vector<uint8_t> direct(c::BLOB);
  {strata::platform::ModelReader reader(argv[1],65536,5000);reader.read_exact(0,direct.data(),direct.size());}
  require(direct==blob,"IOCP expert payload differs from standard loader");
  blob.swap(direct);
#else
  throw std::runtime_error("IOCP requires Windows");
#endif
 }
 c::ActQ act{};act.nchunks=c::H/c::QKA;
 for(int i=0;i<c::H;++i)act.q[i]=int8_t((i%17)-8);
 for(int k=0;k<act.nchunks;++k){act.scale[k]=float((k%7)+1)/64;for(int j=0;j<c::QKA;++j)act.sum[k]+=act.q[k*c::QKA+j];act.hx[k]=act.scale[k]*act.sum[k];}
 std::vector<double> expected_ff(c::FF);std::vector<float> ff(c::FF),out(c::H),single(c::H),other(c::H);
 for(int r=0;r<c::FF;++r){
  double gate=reference_dot(blob.data()+size_t(2*r)*c::ROW_GU,blob.data()+c::O_GU_SCALES+size_t(2*r)*c::SC_GU*2,act,c::H);
  double up=reference_dot(blob.data()+size_t(2*r+1)*c::ROW_GU,blob.data()+c::O_GU_SCALES+size_t(2*r+1)*c::SC_GU*2,act,c::H);
  expected_ff[r]=gate/(1+std::exp(-gate))*up;
 }
 c::portable_gu_rows(blob.data(),act,ff.data(),0,c::FF);double gu_error=check(ff.data(),expected_ff);
 c::ActQ quantized{};c::act_quant_any(ff.data(),c::FF,quantized);std::vector<double> expected(c::H);
 for(int r=0;r<c::H;++r)expected[r]=reference_dot(blob.data()+c::O_D_CODES+size_t(r)*c::ROW_D,blob.data()+c::O_D_SCALES+size_t(r)*c::SC_D*2,quantized,c::FF);
 c::ExpertScratch scratch{};c::expert_cpu_any(blob.data(),act,single.data(),scratch);double down_error=check(single.data(),expected);
 c::ExpertPool pool(1,false,false);c::ExpertJob job;job.blob=blob.data();job.act=&act;job.out=out.data();job.slot=0;
 for(int pass=0;pass<3;++pass){std::fill(out.begin(),out.end(),NAN);if(pass==1)pool.run_split(&job,1);else pool.run(&job,1);check(out.data(),expected);}
 c::ExpertJobMulti group;group.blob=blob.data();group.nt=2;group.act[0]=group.act[1]=&act;group.out[0]=out.data();group.out[1]=other.data();pool.run_split_multi(&group,1);check(out.data(),expected);check(other.data(),expected);
 std::printf("PASS REAL_WEIGHT_CPU_EXPERT; bytes=%zu H=%d FF=%d gu_max_abs_error=%.9g down_max_abs_error=%.9g; ExpertPool single/split/grouped; loader=%s; full_model_inference=false GPU=false\n",blob.size(),c::H,c::FF,gu_error,down_error,iocp?"IOCP exact bytes":"standard");return 0;
}catch(const std::exception& e){std::fprintf(stderr,"FAIL %s\n",e.what());return 1;}}
