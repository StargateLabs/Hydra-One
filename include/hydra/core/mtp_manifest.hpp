#pragma once
#include "hydra/core/checked_memory.hpp"
#include "hydra/core/layout.hpp"
#include <istream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace strata::core {
struct MtpDenseEntry {
    std::string name, kind;
    int64_t rows = 0, cols = 0;
    uint64_t off = 0, bytes = 0;
};
struct MtpDenseManifest { std::vector<MtpDenseEntry> entries; uint64_t bytes = 0; };

inline bool mtp_geometry_supported(const ModelGeometry& g) {
    return g.n_embd == 2560 && g.n_ff == 640 && g.hc == 4 && g.hc_lr == 320 &&
           g.n_head == 24 && g.n_head_kv == 2 && g.head_dim == 256 &&
           g.idx_q_heads == 4 && g.idx_key_dim == 128 && g.n_expert > 0 && g.n_expert <= 512;
}

// This is the format written by tools/mtp_rt.py and read by MtpDrafter.
// Only metadata is parsed; the canonical tensor contracts bound host staging
// before any blob allocation. No weight values are decoded here.
inline bool mtp_dense_manifest(std::istream& input, const ModelGeometry& g,
                               MtpDenseManifest& result, std::string& err) {
    if (!mtp_geometry_supported(g)) { err = "MTP_MANIFEST_GEOMETRY"; return false; }
    using Shape = MtpDenseEntry;
    std::map<std::string, Shape> expected;
    auto add = [&](const std::string& name, const std::string& kind, int64_t rows, int64_t cols) {
        expected.emplace(name, Shape{name,kind,rows,cols,0,0});
    };
    const int64_t n = g.n_embd, d = g.hc * n;
    add("fc_embedding.weight","q8_0",n,n); add("fc_hidden.weight","q8_0",n,n);
    for (const char* prefix : {"hyper_connection_mixer", "attn_hyper_connection", "mlp_hyper_connection"}) {
        const std::string p(prefix);
        add(p+".hc_norm.weight","f32",1,d);
        add(p+".input_mix_weight_down.weight","bf16",g.hc_lr,d);
        add(p+".input_mix_weight_up.weight","bf16",d,g.hc_lr);
        if (p!="hyper_connection_mixer") add(p+".block_inject_weight.weight","bf16",g.hc,d);
    }
    add("mlp.gate.weight","bf16",g.n_expert,n);
    add("mlp.shared_expert.down_proj.weight","q8_0",n,g.n_ff);
    add("mlp.shared_expert.gate_proj.weight","q8_0",g.n_ff,n);
    add("mlp.shared_expert.up_proj.weight","q8_0",g.n_ff,n);
    add("mlp.shared_expert_gate.weight","bf16",1,n);
    add("self_attn.indexer.index_qk_proj.weight","q8_0",(g.idx_q_heads+1)*g.idx_key_dim,n);
    for (const char* side : {"q", "k"}) {
        add(std::string("self_attn.indexer.")+side+"_layernorm.weight","f32",1,g.idx_key_dim);
        add(std::string("self_attn.")+side+"_norm.weight","f32",1,g.head_dim);
    }
    add("self_attn.k_proj.weight","q8_0",g.n_head_kv*g.head_dim,n);
    add("self_attn.v_proj.weight","q8_0",g.n_head_kv*g.head_dim,n);
    add("self_attn.o_proj.weight","q8_0",n,g.n_head*g.head_dim);
    add("self_attn.q_proj.weight","q8_0",2*g.n_head*g.head_dim,n);
    add("pre_fc_norm_embedding.weight","f32",1,n);
    add("pre_fc_norm_hidden.weight","f32",1,d);
    MtpDenseManifest admitted; std::set<std::string> seen;
    char line[4096];
    while (input.getline(line,sizeof line)) {
        if (!*line) continue;
        MtpDenseEntry e; std::string extra;
        std::istringstream fields(line);
        if (!(fields>>e.name>>e.kind>>e.rows>>e.cols>>e.off>>e.bytes) || (fields>>extra)) {
            err="MTP_MANIFEST_FIELDS"; return false;
        }
        const auto found=expected.find(e.name);
        if (found==expected.end() || !seen.insert(e.name).second ||
            e.kind!=found->second.kind || e.rows!=found->second.rows || e.cols!=found->second.cols) {
            err="MTP_MANIFEST_TENSOR_CONTRACT"; return false;
        }
        uint64_t elements, want;
        if (!checked_memory_mul(uint64_t(e.rows),uint64_t(e.cols),elements)) {
            err="MTP_MANIFEST_OVERFLOW"; return false;
        }
        if (e.kind=="q8_0") {
            if (e.cols%32 || !checked_memory_mul(elements/32,34,want)) {
                err="MTP_MANIFEST_Q8_EXTENT"; return false;
            }
        } else if (!checked_memory_mul(elements,e.kind=="bf16"?2:4,want)) {
            err="MTP_MANIFEST_OVERFLOW"; return false;
        }
        // tools/mtp_rt.py aligns each payload to 256 bytes.
        uint64_t aligned;
        if (!checked_memory_add(admitted.bytes,255,aligned)) { err="MTP_MANIFEST_OVERFLOW"; return false; }
        aligned &= ~255ull;
        if (e.bytes!=want || e.off!=aligned ||
            !checked_memory_add(aligned,e.bytes,admitted.bytes)) {
            err="MTP_MANIFEST_BYTE_EXTENT"; return false;
        }
        admitted.entries.push_back(e);
    }
    if (!input.eof() || seen.size()!=expected.size()) { err="MTP_MANIFEST_INCOMPLETE_OR_LINE_LIMIT"; return false; }
    result=std::move(admitted); return true;
}
} // namespace strata::core
