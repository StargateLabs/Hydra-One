#include "hydra/core/native_head.hpp"
#include "hydra/core/checked_memory.hpp"
#include "hydra/artifact/gguf_reader.hpp"
#include "hydra/kernels/iq_kernels.hpp"
#include "hydra/kernels/native_mmvq.hpp"

#include <cuda_runtime.h>
#include "hydra/core/budget_allocator.hpp"
#include <climits>
#include <cstdio>
#include <cstring>
#include <exception>
#include <stdexcept>

namespace strata::core {

NativeHead::~NativeHead() {
    if(storage_)return; // shared graph/direct owners govern the real backing release
    if (quarantined_) return;
    if (scratch_) ::strata::core::budget_device_free(scratch_);
    if (weights_) ::strata::core::budget_device_free(weights_);
}

bool NativeHead::load(const std::vector<std::string>& shards, int64_t n_in, int64_t n_out, std::string& err) {
    if (quarantined_ || weights_ || scratch_) { err = "native head is already owned or quarantined"; return false; }
    if (n_in <= 0 || n_out <= 0 || n_in > INT_MAX || n_out > INT_MAX || n_in % 256) {
        err = "native head requires positive int32 dimensions and whole 256-value rows";
        return false;
    }
    try {
        auto storage=std::make_shared<NativeWeightStorage>();
        storage->weights.reserve(1);
        if(cudaGetDevice(&storage->device)!=cudaSuccess){err="native head: owner device unavailable";return false;}
        // The architecture is the metadata shard's; output.weight comes from whichever shard holds it (shard 2
        // of Unsloth's UD-Q4_K_XL, whose shard 1 holds no tensor).  GgufModel refuses a duplicate across shards.
        const strata::GgufModel model(shards);
        err = strata::check_architecture(model.meta());
        if (!err.empty()) return false;
        size_t at = 0;
        const strata::TensorInfo* tensor = model.find("output.weight", &at);
        const strata::GgufFile& gguf = model.shard(at);
        if (!tensor || !strata::kernels::native_mmvq_supported((int) tensor->type) || tensor->shape.size() != 2 ||
            tensor->shape[0] != (uint64_t) n_in || tensor->shape[1] != (uint64_t) n_out) {
            err = "native head: expected a natively supported output.weight with the canonical head dimensions";
            return false;
        }
        const uint64_t bytes = strata::kernels::native_mmvq_weight_bytes((int) tensor->type, (int) n_in, (int) n_out);
        uint64_t component_bytes;
        size_t free_bytes = 0, total_bytes = 0;
        if (!bytes || !checked_memory_add(bytes, strata::kernels::native_q8_1_bytes((int)n_in,1), component_bytes) ||
            cudaMemGetInfo(&free_bytes,&total_bytes) != cudaSuccess || free_bytes > total_bytes ||
            component_bytes > free_bytes) {
            err = "native head: weights/scratch overflow or current VRAM bound unavailable/exceeded"; return false;
        }
        const uint64_t payload = gguf.file_size() - gguf.data_start();
        if (tensor->offset > payload || bytes > payload - tensor->offset) {
            err = "native head: truncated output.weight payload";
            return false;
        }
        void* weights = nullptr;
        void* scratch = nullptr;
        cudaError_t status = ::strata::core::budget_for(::strata::core::BudgetComponent::Weights).device_alloc(&weights, bytes);
        if (status == cudaSuccess)
            status = ::strata::core::budget_for(::strata::core::BudgetComponent::Workspace).device_alloc(&scratch, strata::kernels::native_q8_1_bytes((int) n_in, 1));
        if (status == cudaSuccess)
            status = cudaMemcpy(weights, gguf.tensor_data(*tensor), bytes, cudaMemcpyHostToDevice);
        if (status != cudaSuccess) {
            if (scratch) ::strata::core::budget_device_free(scratch);
            if (weights) ::strata::core::budget_device_free(weights);
            err = std::string("native head upload: ") + cudaGetErrorString(status);
            return false;
        }
        weights_ = weights;
        scratch_ = scratch;
        storage->weights.push_back(weights);
        storage->scratch=scratch;
        storage_=std::move(storage);
        bytes_ = bytes;
        n_in_ = (int) n_in;
        n_out_ = (int) n_out;
        type_ = (int) tensor->type;
        return true;
    } catch (const std::exception& error) {
        err = std::string("native head: ") + error.what();
        return false;
    }
}

bool NativeHead::run(const float* mixed, float* logits, void* stream, std::string& err) const {
    if (!loaded() || !mixed || !logits || !stream) {
        err = "native head requires loaded weights, device buffers and an explicit stream";
        return false;
    }
    try {
        if (type_ == 13) {
            strata::kernels::native_q5_k_f32(weights_, mixed, scratch_, logits, n_in_, n_out_, 1, stream);
        } else {
            strata::kernels::native_quantize_q8_1(mixed, scratch_, n_in_, 1, stream);
            strata::kernels::native_mmvq(type_, weights_, scratch_, logits, n_in_, n_out_, 1, stream);
        }
    } catch (const std::exception& error) {
        err = std::string("native head launch: ") + error.what();
        return false;
    }
    const cudaError_t status = cudaPeekAtLastError();
    if (status != cudaSuccess) {
        err = std::string("native head launch: ") + cudaGetErrorString(status);
        return false;
    }
    return true;
}

// ================================ plan v0.3 P6: THE NATIVE EMBEDDING ================================

namespace {
const NativeEmbed* g_embed = nullptr;
}
void set_native_embed(const NativeEmbed* e) { g_embed = e; }
const NativeEmbed* native_embed() { return g_embed && g_embed->available() ? g_embed : nullptr; }

NativeEmbed::~NativeEmbed() {
    if (g_embed == this) g_embed = nullptr;
    if(storage_)return;
    if (quarantined_) return;
    if (host_) ::strata::core::budget_host_free(host_);
    else if (dev_) ::strata::core::budget_device_free(const_cast<void*>(dev_));   // the VRAM fallback below
}

void NativeEmbed::quarantine() noexcept {
    if (g_embed == this) g_embed = nullptr;
    quarantined_ = true;
    if(storage_)storage_->quarantined.store(true);
}

bool NativeEmbed::load(const std::vector<std::string>& shards, int64_t n_embd, int64_t n_vocab, std::string& err) {
    if (quarantined_ || host_ || dev_ || n_embd <= 0 || n_vocab <= 0 || n_embd > INT_MAX || n_vocab > INT_MAX || n_embd%256) {
        err = "native embedding: already owned or invalid dimensions"; return false;
    }
    try {
        auto storage=std::make_shared<NativeWeightStorage>();
        storage->weights.reserve(1);
        if(cudaGetDevice(&storage->device)!=cudaSuccess){err="native embedding: owner device unavailable";return false;}
        const strata::GgufModel model(shards);
        // --embd-gguf's one-tensor file (tools/embd_bf16_pack.py) says "strata-embd": only its tensor is checked
        const strata::MetaValue* arch = model.meta().get("general.architecture");
        err = arch != nullptr && arch->s == "strata-embd" ? std::string() : strata::check_architecture(model.meta());
        if (!err.empty()) { err = "native embedding: " + err; return false; }
        size_t at = 0;
        const strata::TensorInfo* t = model.find("token_embd.weight", &at);
        const strata::GgufFile& gguf = model.shard(at);
        if (!t || t->shape.size() != 2 || t->shape[0] != (uint64_t) n_embd || t->shape[1] != (uint64_t) n_vocab ||
            !strata::kernels::embed_type_supported((int) t->type) || n_embd % 256) {
            err = "native embedding: token_embd.weight is absent, of another shape, or of a type without a GPU "
                  "dequantizer";
            return false;
        }
        row_ = strata::kernels::iq_row_bytes((int) t->type, n_embd);
        if (!checked_memory_mul((uint64_t)row_,(uint64_t)n_vocab,bytes_) || !bytes_) {
            err = "native embedding: byte extent overflow"; return false;
        }
        // the table is copied out of the mapping below: a truncated shard must be an error, not a read past EOF
        if (!model.in_bounds(*t, at) || strata::tensor_payload_bytes(*t) != bytes_) {
            err = "native embedding: token_embd.weight's payload is truncated or not " + std::to_string(bytes_) +
                  " B (" + gguf.path() + ")";
            bytes_ = 0;
            return false;
        }
        if (::strata::core::budget_for(::strata::core::BudgetComponent::Weights).host_alloc(&host_, bytes_, cudaHostAllocMapped | cudaHostAllocPortable) != cudaSuccess) {
            // Under WSL2 the driver's pinned/mapped host budget (~1 GiB) can be spent by the GPU contexts
            // themselves (three cards). The table is only gathered from, so keep it in the current device's VRAM
            // instead: it costs its size there and reads faster than over PCIe.
            cudaGetLastError();
            host_ = nullptr;
            void* d = nullptr;
            if (::strata::core::budget_for(::strata::core::BudgetComponent::Weights).device_alloc(&d, bytes_) != cudaSuccess ||
                cudaMemcpy(d, gguf.tensor_data(*t), bytes_, cudaMemcpyHostToDevice) != cudaSuccess) {
                if (d) ::strata::core::budget_device_free(d);
                cudaGetLastError();
                err = "native embedding: cannot pin " + std::to_string(bytes_ >> 20) + " MiB, nor place it in VRAM";
                return false;
            }
            std::fprintf(stderr, "strata: native embedding: cannot pin %llu MiB, kept in VRAM instead\n",
                         (unsigned long long) (bytes_ >> 20));
            dev_ = d;
        } else {
            std::memcpy(host_, gguf.tensor_data(*t), bytes_);
            void* d = nullptr;
#if defined(STRATA_USE_HIP)
            // #325: the Windows HIP stack can refuse the device alias of a mapped allocation (and, when it gives
            // one, it is the host address itself - unified addressing; kernels read it correctly there, a
            // device-to-device copy into it does not land: tests/hip/mapped_alias). The table is only gathered from,
            // so without an alias it goes into VRAM like the unpinnable case above, instead of failing the start.
            if (cudaHostGetDevicePointer(&d, host_, 0) != cudaSuccess || d == nullptr) {
                cudaGetLastError();
                d = nullptr;
                if (::strata::core::budget_for(::strata::core::BudgetComponent::Weights).device_alloc(&d, bytes_) != cudaSuccess ||
                    cudaMemcpy(d, gguf.tensor_data(*t), bytes_, cudaMemcpyHostToDevice) != cudaSuccess) {
                    if (d) ::strata::core::budget_device_free(d);
                    cudaGetLastError();
                    err = "native embedding: no device alias for the mapped table, and no VRAM to copy it into";
                    return false;
                }
                if (::strata::core::budget_host_free(host_)!=cudaSuccess) {
                    (void) ::strata::core::budget_device_free(d);
                    err="native embedding: mapped host release unverified";
                    return false;
                }
                // the destructor frees dev_ when host_ is null
                host_ = nullptr;
                std::fprintf(stderr, "strata: native embedding: no device alias for the mapped table, kept in VRAM\n");
            }
#else
            if (cudaHostGetDevicePointer(&d, host_, 0) != cudaSuccess) {
                err = "native embedding: no device alias for the mapped table";
                return false;
            }
#endif
            dev_ = d;
        }
        type_ = (int) t->type;
        n_embd_ = n_embd;
        n_vocab_ = n_vocab;
        if(host_)storage->host=host_;
        else storage->weights.push_back(const_cast<void*>(dev_));
        storage_=std::move(storage);
        return true;
    } catch (const std::exception& e) {
        err = std::string("native embedding: ") + e.what();
        return false;
    }
}

void NativeEmbed::gather_dev(const int32_t* tokens, int64_t n_tok, float* out, void* stream) const {
    if (!available() || !tokens || !out || n_tok <= 0 || n_tok > INT_MAX)
        throw std::invalid_argument("native embedding: unavailable owner or invalid batch");
    strata::kernels::iq_embed_rows(type_, dev_, row_, tokens, n_tok, n_embd_, out, stream);
}

void NativeEmbed::gather_one(int64_t token, float* out, void* stream) const {
    if (!available() || !out || token < 0 || token >= n_vocab_)
        throw std::invalid_argument("native embedding: unavailable owner or token outside vocabulary");
    strata::kernels::iq_dequant_f32(type_, (const uint8_t*) dev_ + (size_t) token * row_, n_embd_, out, stream);
}

}  // namespace strata::core
