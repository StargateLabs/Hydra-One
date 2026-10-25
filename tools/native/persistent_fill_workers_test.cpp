#include "persistent_fill_workers.hpp"
#include <array>
#include <chrono>
#include <iostream>
#include <stdexcept>
int main(){
 try {
  size_t cases=0;
  for(size_t threads:{1u,2u,4u,8u}) {
   PersistentFillWorkers pool(threads);
   for(size_t round=0;round<100;++round)for(size_t n:{0u,1u,2u,3u,8u,32u,129u}) {
    std::vector<std::atomic<int>> seen(n);for(auto& x:seen)x=0;
    pool.run(n,threads,[&](size_t i){++seen.at(i);if((i+round)%7==0)std::this_thread::yield();});
    for(auto& x:seen)if(x!=1)throw std::runtime_error("lost or duplicated task");++cases;
   }
   bool caught=false;try{pool.run(32,threads,[](size_t i){if(i==3)throw std::runtime_error("injected");});}catch(const std::runtime_error&){caught=true;}
   if(!caught)throw std::runtime_error("exception lost");
   std::atomic<int> completed=0;pool.run(32,threads,[&](size_t){++completed;});if(completed!=32)throw std::runtime_error("reuse after exception failed");++cases;
   std::atomic<int> concurrent=0;std::thread a([&]{for(int i=0;i<30;++i)pool.run(32,threads,[&](size_t){++concurrent;});});
   std::thread b([&]{for(int i=0;i<30;++i)pool.run(32,threads,[&](size_t){++concurrent;});});a.join();b.join();if(concurrent!=1920)throw std::runtime_error("concurrent invocation corruption");++cases;
  }
  std::cout<<"{\"passed\":true,\"cases\":"<<cases<<"}\n";
 }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
}
