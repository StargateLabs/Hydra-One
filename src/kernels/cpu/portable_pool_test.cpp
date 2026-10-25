// Real ExpertPool dispatch with synthetic bytes; never model inference.
#include "hydra/kernels/cpu/pool.hpp"
#include "hydra/kernels/cpu/portable_expert.hpp"
#include "hydra/kernels/cpu/expert_layout.hpp"
#include <vector>
#include <cstring>
#include <cmath>
#include <cstdio>
namespace c=strata::kernels::cpu;
int main(){
 std::vector<uint8_t> blob(c::BLOB,0xaa);uint16_t scale=0x1400;
 for(size_t i=c::O_GU_SCALES;i<c::BLOB;i+=2)std::memcpy(blob.data()+i,&scale,2);
 c::ActQ act{};act.nchunks=c::H/c::QKA;for(int i=0;i<c::H;++i)act.q[i]=1;
 for(int i=0;i<act.nchunks;++i){act.scale[i]=1;act.sum[i]=32;act.hx[i]=32;}
 c::ExpertScratch scratch{};float reference[c::H],out[c::H],second[c::H];
 c::expert_cpu_any(blob.data(),act,reference,scratch);
 c::ExpertPool pool(1,false,false);c::ExpertJob job;job.blob=blob.data();job.act=&act;job.out=out;job.slot=0;
 for(int pass=0;pass<3;++pass){
  std::fill(out,out+c::H,NAN);if(pass==1)pool.run_split(&job,1);else pool.run(&job,1);
  for(int i=0;i<c::H;++i)if(!std::isfinite(out[i])||std::fabs(out[i]-reference[i])>1e-4f)return 1;
 }
 c::ExpertJobMulti group;group.blob=blob.data();group.nt=2;group.act[0]=group.act[1]=&act;group.out[0]=out;group.out[1]=second;
 pool.run_split_multi(&group,1);
 for(int i=0;i<c::H;++i)if(std::fabs(out[i]-reference[i])>1e-4f||std::fabs(second[i]-reference[i])>1e-4f)return 2;
 std::printf("PASS ExpertPool single/split/grouped/repeated batches; kernel=%s; synthetic fixture only; NATIVE_INFERENCE_VERIFIED=false\n",c::cpu_avx512_ok()?"AVX512":"SCALAR_PLANAR_Q2 + AVX2_ACTIVATION");return 0;
}
