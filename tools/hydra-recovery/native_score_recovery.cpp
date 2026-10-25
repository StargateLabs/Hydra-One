#include "llama.h"
#include "json.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
using json=nlohmann::json;

static std::vector<llama_token> tokenize(const llama_vocab* vocab,const std::string& text){
    int n=llama_tokenize(vocab,text.data(),int(text.size()),nullptr,0,true,false);
    if(n>=0)throw std::runtime_error("token capacity contract");
    std::vector<llama_token> tokens(-n);
    int actual=llama_tokenize(vocab,text.data(),int(text.size()),tokens.data(),int(tokens.size()),true,false);
    if(actual<1)throw std::runtime_error("empty tokenization");tokens.resize(actual);return tokens;
}

int main(int argc,char** argv){
    try{
        if(argc!=2)throw std::runtime_error("explicit model required");
        std::string raw;std::getline(std::cin,raw);
        if(raw.size()>32768)throw std::runtime_error("request budget");
        auto request=json::parse(raw);auto prefix=request.at("prefix_text").get<std::string>();
        auto alternatives=request.at("alternatives");auto normalize=request.at("normalize").get<std::string>();
        if(prefix.empty()||prefix.size()>16384||!alternatives.is_array()||alternatives.empty()||alternatives.size()>4||(normalize!="sum"&&normalize!="mean"))throw std::runtime_error("request contract");
        llama_backend_init();
        auto mp=llama_model_default_params();mp.n_gpu_layers=0;mp.load_mode=LLAMA_LOAD_MODE_MMAP;
        std::unique_ptr<llama_model,decltype(&llama_model_free)> model(llama_model_load_from_file(argv[1],mp),llama_model_free);
        if(!model)throw std::runtime_error("model load");
        auto cp=llama_context_default_params();cp.n_ctx=512;cp.n_batch=256;cp.n_ubatch=256;cp.n_threads=2;cp.n_threads_batch=2;
        std::unique_ptr<llama_context,decltype(&llama_free)> ctx(llama_init_from_model(model.get(),cp),llama_free);
        if(!ctx)throw std::runtime_error("context initialization");
        const auto* vocab=llama_model_get_vocab(model.get());const int width=llama_vocab_n_tokens(vocab);
        auto initial=tokenize(vocab,prefix);if(initial.size()>128)throw std::runtime_error("prefix token budget");
        json rows=json::array();bool complete=true;
        for(const auto& alternative:alternatives){
            std::string id=alternative.at("id"),text=alternative.at("text");
            if(id.empty()||id.size()>128||text.empty()||text.size()>4096)throw std::runtime_error("alternative budget");
            auto full=tokenize(vocab,prefix+text);
            if(full.size()>256)throw std::runtime_error("full token budget");
            if(full.size()<=initial.size()||!std::equal(initial.begin(),initial.end(),full.begin())){
                rows.push_back({{"id",id},{"status","unscorable_boundary"},{"tokens",json::array()}});complete=false;continue;
            }
            llama_memory_clear(llama_get_memory(ctx.get()),true);
            if(llama_decode(ctx.get(),llama_batch_get_one(initial.data(),int(initial.size()))))throw std::runtime_error("prefix decode");
            json scores=json::array();double total=0;
            for(size_t i=initial.size();i<full.size();++i){
                auto* logits=llama_get_logits_ith(ctx.get(),-1);if(!logits)throw std::runtime_error("missing logits");
                double maximum=*std::max_element(logits,logits+width),sum=0;
                for(int k=0;k<width;++k)sum+=std::exp(double(logits[k])-maximum);
                double logprob=double(logits[full[i]])-maximum-std::log(sum);
                if(!std::isfinite(logprob))throw std::runtime_error("nonfinite log probability");
                total+=logprob;scores.push_back({{"token_id",full[i]},{"logprob",logprob}});
                if(i+1<full.size()){
                    llama_token token=full[i];if(llama_decode(ctx.get(),llama_batch_get_one(&token,1)))throw std::runtime_error("continuation decode");
                }
            }
            rows.push_back({{"id",id},{"status","complete"},{"tokens",scores},{"score",normalize=="mean"?total/scores.size():total},{"sum_logprob",total}});
        }
        json result={{"status",complete?"complete":"incomplete"},{"alternatives",rows},{"normalize",normalize},{"calibrated_probabilities",false},{"native",true},{"provenance",{{"backend","recovered-llama-cpu-capi"},{"tokenizer","model-native; exact UTF8 prefix boundary verified"},{"gpu",false},{"prefix_cache",false}}}};
        std::cout<<result.dump()<<std::endl;
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<std::endl;return 1;}
}
