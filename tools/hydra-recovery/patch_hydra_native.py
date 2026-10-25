from pathlib import Path
root=Path(__file__).resolve().parents[2]/'hydra-engine/engine_completion_v22/prism-source'
project=Path(__file__).resolve().parents[2]
p=root/'src/llama-mmap.cpp';s=p.read_text()
assert 'hydra_read_tensor' not in s
s=s.replace('#include "ggml.h"','#include "ggml.h"\n#include "hydra/platform/model_reader.hpp"\n#include <cstdlib>',1)
s=s.replace('    HANDLE fp_win32;','''    HANDLE fp_win32;
    std::string hydra_filename;
    std::unique_ptr<strata::platform::ModelReader> hydra_reader;
    uint64_t hydra_bytes=0;
    bool hydra_announced=false;
    bool hydra_iocp() const {
        const char* mode=std::getenv("HYDRA_MODEL_IO");
        if (mode && std::strcmp(mode,"standard") && std::strcmp(mode,"iocp"))
            throw std::runtime_error("HYDRA invalid model IO mode");
        return mode && !std::strcmp(mode,"iocp");
    }
    void hydra_read_tensor(void* destination,size_t bytes) {
        const bool iocp=hydra_iocp();
        if(!hydra_announced){
            std::fprintf(stderr,"HYDRA_LOADER mode=%s consumer=llama_file::read_raw\\n",iocp?"iocp":"standard");
            hydra_announced=true;
        }
        if(iocp){
            if(hydra_filename.empty())throw std::runtime_error("HYDRA IOCP requires named file");
            if(!hydra_reader)hydra_reader=std::make_unique<strata::platform::ModelReader>(hydra_filename);
            size_t offset=tell();hydra_reader->read_exact(offset,destination,bytes);seek(offset+bytes,SEEK_SET);
        }else read_raw(destination,bytes);
        hydra_bytes+=bytes;
    }''',1)
s=s.replace('        fp = ggml_fopen(fname, mode);','        hydra_filename=fname;\n        fp = ggml_fopen(fname, mode);',1)
s=s.replace('    ~impl() {','''    ~impl() {
        hydra_reader.reset();
        if(hydra_announced)std::fprintf(stderr,"HYDRA_READER mode=%s consumer_bytes=%llu cleanup=closed\\n",hydra_iocp()?"iocp":"standard",(unsigned long long)hydra_bytes);''',1)
needle='void llama_file::read_raw(void * ptr, size_t len) { pimpl->read_raw(ptr, len); }'
assert needle in s
s=s.replace(needle,needle+'''
void llama_file::hydra_read_tensor(void * ptr, size_t len) {
#ifdef _WIN32
    pimpl->hydra_read_tensor(ptr,len);
#else
    pimpl->read_raw(ptr,len);
#endif
}''',1)
p.write_text(s)
p=root/'src/llama-mmap.h';s=p.read_text();s=s.replace('    void read_raw(void * ptr, size_t len);','    void read_raw(void * ptr, size_t len);\n    void hydra_read_tensor(void * ptr, size_t len);',1);p.write_text(s)
p=root/'src/llama-model-loader.cpp';s=p.read_text();assert s.count('file->read_raw(')==3
s=s.replace('file->read_raw(','file->hydra_read_tensor(')
# Windows does not use the POSIX direct-I/O aligned path.
p.write_text(s)
p=root/'src/CMakeLists.txt';s=p.read_text();s+='\n# Recovered HYDRA CPU IOCP consumer; isolated build only.\ntarget_sources(llama PRIVATE "'+(project/'src/platform/direct_file.cpp').as_posix()+'")\ntarget_include_directories(llama PRIVATE "'+(project/'include').as_posix()+'")\n';p.write_text(s)
print('Patched isolated native source; production source and binaries unchanged')
