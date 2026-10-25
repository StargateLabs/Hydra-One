// include/hydra/kernels/cpu/expert_layout.hpp - plan v0.3 P6: where each routed expert lives in experts.bin.
//
// A Q2_0 pack (tools/strata_pack.py) has one blob size for every layer, `BLOB`, in the Strata expert form.  A
// native pack (tools/iq_pack.py, the IQ2_XS / IQ3_XXS files) keeps each expert's raw GGUF slices, so the blob
// size and the formats change from layer to layer; `native_experts.txt` says how.  Everything that touches an
// expert blob - the arena, the VRAM tier, the prompt path, the CPU pool, the GPU window - asks this table.
#pragma once

#include "hydra/kernels/cpu/expert.hpp"
#include "hydra/kernels/cpu/native_expert.hpp"

#include <cstdint>
#include <string>
#include <vector>
#include <limits>
#include <stdexcept>

namespace strata::kernels::cpu {

struct ExpertLayout {
    bool native = false;
    int64_t n_layers = 0, n_expert = NE;
    std::vector<NativeFmt> fmt;           ///< per layer (native packs)
    std::vector<uint64_t> offset, bytes;  ///< per layer: where its 512 blobs start, bytes per blob
    /// Plan v0.3 P6: per layer, the absolute offsets of the gate / up / down tensors in their GGUF files, so the
    /// arena can be filled from the GGUF itself when the pack has no experts.bin (3 x n_layers, 0 = unknown).
    std::vector<uint64_t> gguf_off;
    /// Per layer PER ROLE (3 x n_layers, `3 * layer + role`, matching `gguf_off`), the GGUF file - a name beside
    /// the --native shard - that holds that role's tensor.  Empty = the --native shard itself.  Per role because a
    /// shard boundary can fall inside a layer: Unsloth's UD-Q4_K_XL has layer 11's down in shard 2 and its gate
    /// and up in shard 3 (native_experts.txt v4, the `gate,up,down` shard column).
    std::vector<std::string> gguf_file;
    int version = 0;                      ///< native_experts.txt's header version (0 = none given)
    uint64_t max_blob = BLOB;
    uint64_t total = 0;                   ///< experts.bin size

    void check_layer(int64_t layer) const {
        if(layer<0 || n_expert<=0 || (n_layers>0 && layer>=n_layers))throw std::out_of_range("EXPERT_LAYOUT_LAYER");
    }
    static uint64_t product(uint64_t a,uint64_t b) {
        if(b && a>std::numeric_limits<uint64_t>::max()/b)throw std::overflow_error("EXPERT_LAYOUT_SIZE_OVERFLOW");
        return a*b;
    }
    uint64_t blob_bytes(int64_t layer) const {
        check_layer(layer);
        if(native && ((size_t)layer>=bytes.size() || bytes[(size_t)layer]==0))throw std::out_of_range("EXPERT_LAYOUT_PAYLOAD");
        return native ? bytes[(size_t)layer] : (uint64_t)BLOB;
    }
    uint64_t layer_offset(int64_t layer) const {
        check_layer(layer);
        if(native && (size_t)layer>=offset.size())throw std::out_of_range("EXPERT_LAYOUT_OFFSET");
        return native ? offset[(size_t)layer] : product(product((uint64_t)layer,(uint64_t)n_expert),(uint64_t)BLOB);
    }
    uint64_t blob_offset(int64_t layer, int64_t expert) const {
        if(expert<0 || expert>=n_expert)throw std::out_of_range("EXPERT_LAYOUT_EXPERT");
        const uint64_t base=layer_offset(layer),size=blob_bytes(layer),delta=product((uint64_t)expert,size);
        if(delta>std::numeric_limits<uint64_t>::max()-base)throw std::overflow_error("EXPERT_LAYOUT_OFFSET_OVERFLOW");
        const uint64_t at=base+delta;
        if(total && (at>total || size>total-at))throw std::out_of_range("EXPERT_LAYOUT_FILE_BUDGET");
        return at;
    }
};

/// Plan v0.3 P6: whether this CPU (and its OS) runs the AVX-512 kernels (F, BW, VL, VNNI, VBMI).  Probed in a
/// file compiled without AVX-512, so asking is safe everywhere; STRATA_FORCE_AVX2=1 answers no (for tests).
bool cpu_avx512_ok();
/// Whether this CPU (and its OS) runs the AVX2 kernels (AVX, AVX2, FMA, F16C): the floor of every expert kernel
/// (q2_avx2.cpp, iq_avx2.cpp, and ggml-cpu in the portable build).  STRATA_FORCE_AVX2 does not change it.
bool cpu_avx2_ok();
/// The CPU's brand string (CPUID 0x80000002..4), for messages; "unknown" when it has none.
std::string cpu_name();
/// Q2_0 GGUF rows / activation quantizer on the kernels this CPU has.
void q2_rows_any(const uint8_t* w, size_t row_bytes, int nblocks, const ActQ* const* a, int nt, float* const* out,
                 int r0, int r1);
void act_quant_any(const float* x, int n, ActQ& a);

/// The process-wide layout (canonical Q2_0 until `expert_layout_load` finds a native pack).
const ExpertLayout& expert_layout();
/// Reads `<pack_dir>/native_experts.txt` when it exists (a native pack), else sets the canonical layout.
/// Versions up to kExpertLayoutVersion are read; a newer one is refused (a newer packer wrote it).
bool expert_layout_load(const std::string& pack_dir, int64_t n_layers, int64_t n_expert, std::string& err);
/// The newest native_experts.txt this engine reads.  v4 = v3 plus the per-role shard column `gate,up,down`,
/// written only when some layer's roles are in different shards (every other pack stays v3, byte for byte).
inline constexpr int kExpertLayoutVersion = 4;

}  // namespace strata::kernels::cpu
