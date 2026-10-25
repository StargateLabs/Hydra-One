// src/core/weights.cpp - the dense-weight loader.  See the header for the engine-vs-pack distinction.
#include "hydra/core/weights.hpp"

#include "hydra/kernels/f16_bits.hpp"

#include <cuda_runtime.h>
#include "hydra/core/budget_allocator.hpp"
#include "hydra/core/checked_memory.hpp"
#include "hydra/core/on_device.hpp"

#include <chrono>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#if defined(_WIN32)
#include <io.h>
#else
#include <unistd.h>
#endif

namespace strata::core {
// The backing owner belongs to the loader's core library. Keeping its destructor
// in strata_engine makes otherwise core-only WeightTable consumers depend on an
// upper layer (and on its kernels) just to destroy a weak/shared owner.
NativeWeightStorage::~NativeWeightStorage() {
    if(quarantined.load() || (weights.empty()&&!scratch&&!host))return;
    const OnDevice on(device);
    int current=-1;
    auto retain=[] {std::fprintf(stderr,"native weights: teardown incomplete; remaining backing claims retained\n");};
    if(device<0 || cudaGetDevice(&current)!=cudaSuccess || current!=device ||
       cudaDeviceSynchronize()!=cudaSuccess){retain();return;}
    if(scratch && budget_device_free(scratch)!=cudaSuccess){retain();return;}
#if defined(CUDART_VERSION) || defined(STRATA_USE_HIP)
    if(host && budget_host_free(host)!=cudaSuccess){retain();return;}
#else
    if(host && cudaFreeHost(host)!=cudaSuccess){retain();return;}
#endif
    for(void* pointer:weights)if(budget_device_free(pointer)!=cudaSuccess){retain();return;}
}

namespace {

constexpr uint64_t CHUNK = 8ull << 20;   // 8 MiB of SOURCE per staging round

cudaError_t allocate_staging(void** pointer, size_t bytes, unsigned flags) {
#if defined(CUDART_VERSION) || defined(STRATA_USE_HIP)
    return budget_for(BudgetComponent::Staging).host_alloc(pointer, bytes, flags);
#else
    return cudaHostAlloc(pointer, bytes, flags);
#endif
}
cudaError_t free_staging(void*& pointer) {
    void* owned=pointer;
    pointer=nullptr; // one release attempt; uncertain managed frees retain the ledger entry
#if defined(CUDART_VERSION) || defined(STRATA_USE_HIP)
    return budget_host_free(owned);
#else
    return cudaFreeHost(owned);
#endif
}
struct StagingOwner {
    void*& input;
    void*& output;
    ~StagingOwner(){if(input)free_staging(input);if(output)free_staging(output);}
};

double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

struct IndexRow {
    std::string name;
    int file = 0;
    WeightKind kind = WeightKind::Verbatim;
    uint64_t src_off = 0, src_bytes = 0, dst_off = 0, dst_bytes = 0;
    int64_t ne0 = 0, ne1 = 0;
    int code_bits = 0, code_bias = 0, group_elems = 0, codebook = 0, has_offset = 0;
    uint64_t codes_bytes = 0, scales_bytes = 0, offset_bytes = 0;
    int scales_fp16 = 0;
    int act_kind = 0;
    bool raw16 = false;   ///< plan v0.3 P6: already 16-bit in the file (kinds 4/5)
};

/// How a segment's bytes must be transformed on the way from the pack to the arena.
enum class Conv : int {
    Copy = 0,      ///< the bytes are already the engine form
    Bf16High = 1,  ///< f32 container holding a bf16 value: take the high 16 bits
    ToF16 = 2,     ///< f32 container holding an f16 value: a real round-to-nearest-even conversion
    WidenF16 = 3,  ///< fp16 bits to be held as f32: EXACT, and the reason this path exists at all
};

/// One contiguous run of a tensor's source span with a single destination range and one transform.
///
/// THE SEGMENT LIST IS WHY THIS LOADER CAN CHANGE WIDTHS PLANE BY PLANE.  A quantized tensor used to be one
/// verbatim span, which is only correct when every plane is already in engine form - and for 90 of the 303
/// quantized tensors the scale plane is fp16 in the pack and must be f32 in the arena.
struct Seg {
    uint64_t src_off = 0;   ///< relative to the row's src_off
    uint64_t src_bytes = 0;
    uint64_t dst_off = 0;   ///< relative to the row's dst_off
    uint64_t dst_bytes = 0;
    Conv conv = Conv::Copy;
};

const char* file_name(int id) {
    switch (id) {
        case 0: return "dense.bin";
        case 1: return "embd.bin";
        case 2: return "experts.bin";
        case 3: return "extra.bin";   // plan v0.3 P6: a native pack's float tensors that the base pack quantized
        default: return nullptr;
    }
}

/// UTF-16 path for CreateFile-free portability: the loader uses `std::fopen`, which on Windows takes an ANSI
/// path.  The pack lives beside the executable in practice, but a pack under a user directory with a
/// non-ASCII name would silently fail to open, so the caller gets the errno rather than a null pointer.
bool read_at(std::FILE* f, uint64_t off, void* dst, size_t n, std::string& err, const char* what) {
#if defined(_WIN32)
    if (_fseeki64(f, (long long) off, SEEK_SET) != 0) { err = std::string(what) + ": seek failed"; return false; }
#else
    if (fseeko(f, (off_t) off, SEEK_SET) != 0) { err = std::string(what) + ": seek failed"; return false; }
#endif
    if (std::fread(dst, 1, n, f) != n) { err = std::string(what) + ": short read"; return false; }
    return true;
}

}  // namespace

bool WeightTable::pool_bytes(const std::string& pack_dir, uint64_t& out, std::string& err,
                             const std::set<std::string>* skip) {
    const std::string path = pack_dir + "/index.txt";
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) { err = "cannot open " + path; return false; }
    char line[1024];
    out = 0;
    uint64_t pool = 0, compact = 0;
    int align = 0;
    while (std::fgets(line, sizeof line, f)) {
        if (line[0] == '#') {
            unsigned long long p = 0;
            int a = 0, tensors = 0;
            if (std::sscanf(line, "# align %d pool %llu tensors %d", &a, &p, &tensors) == 3) { pool = p; align = a; }
            continue;
        }
        if (skip == nullptr) continue;
        char name[256] = {0};
        unsigned long long dst_bytes = 0, dummy = 0;
        int i1 = 0, i2 = 0;
        if (std::sscanf(line, "%255s %d %d %llu %llu %llu %llu", name, &i1, &i2, &dummy, &dummy, &dummy, &dst_bytes) != 7)
            continue;
        if (skip->count(name)) continue;
        const uint64_t a = align > 0 ? (uint64_t) align : 256;
        uint64_t padded, rounded;
        if (!checked_memory_add(dst_bytes,a-1,padded) ||
            !checked_memory_mul(padded/a,a,rounded) ||
            !checked_memory_add(compact,rounded,compact)) {
            std::fclose(f); err="weight table: compacted arena size overflow"; return false;
        }
    }
    std::fclose(f);
    if (pool == 0 || pool > kMemoryExtentMax) { err = "missing or unrepresentable arena bound in " + path; return false; }
    out = skip ? compact : pool;
    return true;
}

bool WeightTable::index_code_bits(const std::string& pack_dir, const std::string& name, int& code_bits,
                                  std::string& err) {
    const std::string path = pack_dir + "/index.txt";
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (!f) { err = "cannot open " + path; return false; }
    char line[1024];
    code_bits = -1;
    while (std::fgets(line, sizeof line, f)) {
        if (line[0] == '#') continue;
        char row[256] = {0};
        unsigned long long dummy = 0;
        long long ne = 0;
        int i1 = 0, i2 = 0, bits = 0;
        // the first ten fields of the row `load` parses: name file kind src_off src_bytes dst_off dst_bytes ne0 ne1 code_bits
        if (std::sscanf(line, "%255s %d %d %llu %llu %llu %llu %lld %lld %d", row, &i1, &i2, &dummy, &dummy, &dummy,
                        &dummy, &ne, &ne, &bits) != 10)
            continue;
        if (name == row) { code_bits = bits; break; }
    }
    std::fclose(f);
    return true;
}

bool WeightTable::load(const std::string& pack_dir, void* arena_base, uint64_t arena_bytes, std::string& err,
                       const std::set<std::string>* skip) {
    for (const auto& item : table_) if (item.second.native_data || !item.second.native_owner.expired()) {
        err = "weight table reload refused: native projection owner is still attached";
        return false;
    }
    const std::string path = pack_dir + "/index.txt";
    std::FILE* idx = std::fopen(path.c_str(), "rb");
    if (!idx) { err = "cannot open " + path + " (run tools/pack_index.py)"; return false; }

    uint64_t pool = 0;
    int align = 0;
    std::vector<IndexRow> rows;
    char line[1024];
    while (std::fgets(line, sizeof line, idx)) {
        if (line[0] == '#') {
            unsigned long long p = 0;
            int a = 0, t = 0;
            if (std::sscanf(line, "# align %d pool %llu tensors %d", &a, &p, &t) == 3) { pool = p; align = a; }
            continue;
        }
        IndexRow r;
        char name[256] = {0};
        int kind = 0;
        // The format is written by tools/pack_index.py and is space-separated with no quoting; a name with a
        // space in it would break the parse, which is why the parser REFUSES rather than taking what it got.
        const int n = std::sscanf(line,
                                  "%255s %d %d %llu %llu %llu %llu %lld %lld %d %d %d %d %d %llu %llu %llu %d %d",
                                  name, &r.file, &kind, &r.src_off, &r.src_bytes, &r.dst_off, &r.dst_bytes,
                                  &r.ne0, &r.ne1, &r.code_bits, &r.code_bias, &r.group_elems, &r.codebook,
                                  &r.has_offset, &r.codes_bytes, &r.scales_bytes, &r.offset_bytes,
                                  &r.scales_fp16, &r.act_kind);
        if (n != 19) {
            // A malformed index line is a WRONG BYTE OFFSET waiting to happen, and a wrong offset decodes to
            // a plausible weight.  Refuse loudly instead of loading the rows that happened to parse.
            err = "index.txt: could not parse a row (" + std::to_string(n) + " of 19 fields)";
            std::fclose(idx);
            return false;
        }
        r.name = name;
        // plan v0.3 P6: a standalone native pack (tools/iq_pack.py) stores 16-bit floats as they are in the GGUF:
        // index kinds 4 (BF16) and 5 (F16) are copied and take the engine forms of kinds 1 and 3
        if (kind == 4 || kind == 5) {
            r.raw16 = true;
            kind = kind == 4 ? (int) WeightKind::Bf16InF32 : (int) WeightKind::F16InF32;
        }
        r.kind = (WeightKind) kind;
        rows.push_back(r);
    }
    std::fclose(idx);

    if (pool == 0 || rows.empty()) { err = "index.txt has no header or no rows"; return false; }
    // Plan v0.3 P1: a skip set compacts the arena.  Kept rows are re-placed in index order at the index's
    // alignment; skipped rows keep their metadata and get no bytes.
    std::vector<bool> skipped(rows.size(), false);
    if (skip != nullptr) {
        const uint64_t a = align > 0 ? (uint64_t) align : 256;
        uint64_t at = 0;
        for (size_t i = 0; i < rows.size(); ++i) {
            if (skip->count(rows[i].name)) { skipped[i] = true; continue; }
            rows[i].dst_off = at;
            uint64_t padded, rounded;
            if (!checked_memory_add(rows[i].dst_bytes,a-1,padded) ||
                !checked_memory_mul(padded/a,a,rounded) ||
                !checked_memory_add(at,rounded,at)) {
                err="weight table: compacted arena size overflow"; return false;
            }
        }
        pool = at;
    }
    std::set<std::string> unique_names;
    for(size_t i=0;i<rows.size();++i) {
        const auto& r=rows[i];
        uint64_t source_end, destination_end, plane_bytes, elements;
        if(!unique_names.insert(r.name).second || !file_name(r.file) || r.ne0<=0 || r.ne1<0 ||
           !checked_memory_mul((uint64_t)r.ne0,(uint64_t)(r.ne1>0?r.ne1:1),elements) ||
           !checked_memory_add(r.src_off,r.src_bytes,source_end) ||
           !checked_memory_add(r.codes_bytes,r.scales_bytes,plane_bytes) ||
           !checked_memory_add(plane_bytes,r.offset_bytes,plane_bytes) ||
           (!skipped[i] && (!checked_memory_add(r.dst_off,r.dst_bytes,destination_end) || destination_end>pool))) {
            err="weight table: duplicate name, invalid geometry, offset or plane extent: "+r.name;
            return false;
        }
    }
    if (pool>kMemoryExtentMax || arena_bytes>kMemoryExtentMax || arena_bytes < pool || (pool && !arena_base)) {
        err = "arena is " + std::to_string(arena_bytes) + " B but the index needs " + std::to_string(pool);
        return false;
    }

    // Two pinned staging buffers, both reused.  Pinned because a 5 GB pageable upload spends its time in the
    // driver copying through a bounce buffer, and bounded by CHUNK rather than by the largest tensor.
    //
    // STAGE_OUT IS NOT OPTIONAL.  The first version of this loop converted the values straight into the
    // destination pointer - which is DEVICE memory - from host code.  A host write to a device address is
    // undefined behaviour, and on this driver it does not fault: it corrupts whatever the address maps to in
    // the host's own space, which is nothing at all, so the tensor would have loaded as the UNCONVERTED pack
    // bytes and every BF16 weight would have been read as 32-bit garbage.  Converted data goes to a host
    // buffer and crosses the bus once.
    //
    // STAGE_OUT IS TWICE STAGE_IN because a conversion can now GROW: widening an fp16 scale plane to f32
    // doubles it.  Sized at CHUNK it would have written 8 MiB past the end of a pinned allocation for every
    // one of the 90 widened tensors - a heap corruption that would have been blamed on whatever ran next.
    void* stage_in = nullptr;
    void* stage_out = nullptr;
    StagingOwner staging_owner{stage_in,stage_out};
    if (allocate_staging(&stage_in, CHUNK, cudaHostAllocDefault) != cudaSuccess ||
        allocate_staging(&stage_out, CHUNK * 2, cudaHostAllocDefault) != cudaSuccess) {
        err = "cudaHostAlloc for the staging buffers failed";
        if (stage_in) free_staging(stage_in);
        if (stage_out) free_staging(stage_out);
        return false;
    }

    uint8_t* dst_base = (uint8_t*) arena_base;
    std::FILE* cur = nullptr;
    std::unique_ptr<std::FILE,decltype(&std::fclose)> current_file(nullptr,&std::fclose);
    int cur_file = -1;
    table_.clear();
    report_ = LoadReport{};

    const double t_read0 = now_ms();
    double upload_ms = 0;
    for (size_t row_i = 0; row_i < rows.size(); ++row_i) {
        const IndexRow& r = rows[row_i];
        if (skipped[row_i]) {
            WeightRef wr;
            wr.data = nullptr;
            wr.resident = false;
            wr.bytes = r.dst_bytes;
            wr.ne0 = r.ne0;
            wr.ne1 = r.ne1;
            wr.elements = r.ne0 * (r.ne1 > 0 ? r.ne1 : 1);
            wr.kind = r.kind;
            wr.code_bits = r.code_bits;
            wr.code_bias = r.code_bias;
            wr.group_elems = r.group_elems;
            wr.codebook_iq4nl = r.codebook != 0;
            wr.has_offset = r.has_offset != 0;
            wr.codes_bytes = r.codes_bytes;
            wr.scales_bytes = r.scales_bytes;
            wr.offset_bytes = r.offset_bytes;
            wr.src_off = r.src_off;
            wr.src_bytes = r.src_bytes;
            wr.file_id = r.file;
            wr.scales_fp16 = r.scales_fp16 != 0;
            wr.act_kind = r.act_kind;
            table_[r.name] = wr;
            ++report_.tensors;
            continue;
        }
        if (r.code_bits != 0 && r.dst_bytes == 0) {
            // plan v0.3 P6: a native pack's row that carries a shape only - the GGUF form must serve it
            err = r.name + ": this pack holds the tensor only in its GGUF form (run with --native SHARD1)";
            free_staging(stage_in); free_staging(stage_out);
            return false;
        }
        if (r.file != cur_file) {
            current_file.reset();
            cur=nullptr;
            const char* fn = file_name(r.file);
            const std::string p = pack_dir + "/" + (fn ? fn : "?");
            cur = std::fopen(p.c_str(), "rb");
            current_file.reset(cur);
            if (!cur) { err = "cannot open " + p; free_staging(stage_in); free_staging(stage_out); return false; }
            cur_file = r.file;
        }

        // ---- the segment list: what this tensor's bytes are, plane by plane, in both forms
        Seg segs[3];
        int n_segs = 0;
        bool bad = false;
        uint64_t sum_src = 0, sum_dst = 0;
        if (r.codes_bytes != 0) {
            // A quantized tensor: codes, then scales, then the optional offset plane, each contiguous in the
            // source span in that order (pack_index.py verifies the contiguity and refuses otherwise).
            segs[n_segs++] = Seg{0, r.codes_bytes, 0, r.codes_bytes, Conv::Copy};
            if (r.scales_bytes) {
                const uint64_t src_scale_bytes = r.scales_fp16 ? r.scales_bytes / 2 : r.scales_bytes;
                if (r.scales_fp16 && (r.scales_bytes % 2 || src_scale_bytes * 2 != r.scales_bytes)) {
                    err = r.name + ": an fp16 scale plane of an odd byte count";
                    bad = true;
                }
                segs[n_segs++] = Seg{r.codes_bytes, src_scale_bytes, r.codes_bytes, r.scales_bytes,
                                     r.scales_fp16 ? Conv::WidenF16 : Conv::Copy};
            }
            if (r.offset_bytes) {
                const uint64_t after = r.codes_bytes + (r.scales_fp16 ? r.scales_bytes / 2 : r.scales_bytes);
                segs[n_segs++] = Seg{after, r.offset_bytes, r.codes_bytes + r.scales_bytes, r.offset_bytes,
                                     Conv::Copy};
            }
        } else {
            // Everything else is one run whose transform is the row's kind.  The two promoted types shrink
            // 4 B/elem to 2; the rest are already the engine form.
            Conv c = Conv::Copy;
            if (r.raw16) c = Conv::Copy;
            else if (r.kind == WeightKind::Bf16InF32) c = Conv::Bf16High;
            else if (r.kind == WeightKind::F16InF32) c = Conv::ToF16;
            const uint64_t elems = (uint64_t) r.ne0 * (uint64_t) (r.ne1 > 0 ? r.ne1 : 1);
            uint64_t source_size=0,destination_size=0;
            if(c!=Conv::Copy && (!checked_memory_mul(elems,4,source_size) ||
                                !checked_memory_mul(elems,2,destination_size))) {
                err=r.name+": promoted tensor byte extent overflow";bad=true;
            }
            if (!bad && c != Conv::Copy && (r.src_bytes != source_size || r.dst_bytes != destination_size)) {
                // A promoted type is 4 B/elem in and 2 B/elem out, and nothing else.  If those two numbers do
                // not say so, the shape and the byte counts disagree and the element count this loop would
                // use to walk the source is not the element count the pack wrote.
                char buf[320];
                std::snprintf(buf, sizeof buf,
                              "%s: a promoted tensor of %llu elements is %llu B in and %llu B out, not %llu/%llu",
                              r.name.c_str(), (unsigned long long) elems, (unsigned long long) r.src_bytes,
                              (unsigned long long) r.dst_bytes, (unsigned long long) source_size,
                              (unsigned long long) destination_size);
                err = buf;
                bad = true;
            }
            segs[n_segs++] = Seg{0, r.src_bytes, 0, r.dst_bytes, c};
        }
        for (int i = 0; i < n_segs; ++i) { sum_src += segs[i].src_bytes; sum_dst += segs[i].dst_bytes; }
        // The segment list is this loop's own idea of the layout, and it is the ONLY thing standing between a
        // mis-sized plane and a wrong byte offset.  It is checked against both recorded totals, not trusted.
        if (!bad && (sum_src != r.src_bytes || sum_dst != r.dst_bytes)) {
            char buf[360];
            std::snprintf(buf, sizeof buf,
                          "%s: the segments cover %llu/%llu B but the index says %llu/%llu - the plane layout "
                          "this loader built is not the one the index describes",
                          r.name.c_str(), (unsigned long long) sum_src, (unsigned long long) sum_dst,
                          (unsigned long long) r.src_bytes, (unsigned long long) r.dst_bytes);
            err = buf;
            bad = true;
        }
        if (bad) { free_staging(stage_in); free_staging(stage_out); return false; }

        for (int si = 0; si < n_segs; ++si) {
            const Seg& s = segs[si];
            const bool widening = (s.conv == Conv::WidenF16);
            if (widening && (s.src_bytes & 1ull)) {
                err = r.name + ": an fp16 plane with an odd source byte count";
                free_staging(stage_in); free_staging(stage_out);
                return false;
            }
            uint64_t done = 0;
            while (done < s.src_bytes) {
                uint64_t n = std::min(CHUNK, s.src_bytes - done);
                // WIDENING NEVER SPLITS AN ELEMENT.  CHUNK is even, so a full chunk cannot, but the tail of a
                // plane whose length is odd would - and half an fp16 is a plausible-looking scale.
                if (widening && (n & 1ull)) {
                    if (n == 1) { err = r.name + ": an fp16 plane ending on a half element"; free_staging(stage_in); free_staging(stage_out); return false; }
                    n -= 1;
                }
                if (!read_at(cur, r.src_off + s.src_off + done, stage_in, (size_t) n, err, r.name.c_str())) {
                    free_staging(stage_in); free_staging(stage_out);
                    return false;
                }
                const uint8_t* src = (const uint8_t*) stage_in;
                const void* host_src = src;
                uint64_t out_bytes = n;
                uint64_t out_at = s.dst_off + done;

                switch (s.conv) {
                    case Conv::Copy:
                        break;
                    case Conv::Bf16High: {
                        // THE HIGH 16 BITS ARE THE BF16 ENCODING, exactly - not a rounding.  A bf16 value is
                        // the top half of its f32 image, and the pack promoted it without changing it, so
                        // this is a copy with a stride.
                        const uint64_t elems = n / 4;
                        out_bytes = elems * 2;
                        uint8_t* o = (uint8_t*) stage_out;
                        for (uint64_t i = 0; i < elems; ++i) {
                            uint32_t v;
                            std::memcpy(&v, src + i * 4, 4);
                            const uint16_t h = (uint16_t) (v >> 16);
                            std::memcpy(o + i * 2, &h, 2);
                        }
                        host_src = stage_out;
                        out_at = s.dst_off + done / 2;
                        break;
                    }
                    case Conv::ToF16: {
                        const uint64_t elems = n / 4;
                        out_bytes = elems * 2;
                        uint8_t* o = (uint8_t*) stage_out;
                        for (uint64_t i = 0; i < elems; ++i) {
                            float v;
                            std::memcpy(&v, src + i * 4, 4);
                            const uint16_t h = strata::kernels::f16_from_f32(v);
                            std::memcpy(o + i * 2, &h, 2);
                        }
                        host_src = stage_out;
                        out_at = s.dst_off + done / 2;
                        break;
                    }
                    case Conv::WidenF16: {
                        // fp16 bits -> f32.  EXACT: every fp16 value is an f32 value, including the
                        // subnormals, so this cannot change a single weight - which is why the engine may do
                        // it at all, and why doing it costs 10.88 MiB rather than a second kernel family.
                        const uint64_t elems = n / 2;
                        out_bytes = elems * 4;
                        float* o = (float*) stage_out;
                        for (uint64_t i = 0; i < elems; ++i) {
                            uint16_t h;
                            std::memcpy(&h, src + i * 2, 2);
                            o[i] = strata::kernels::f32_from_f16(h);
                        }
                        host_src = stage_out;
                        out_at = s.dst_off + done * 2;
                        break;
                    }
                }

                const double u0 = now_ms();
                if (cudaMemcpy(dst_base + r.dst_off + out_at, host_src, out_bytes, cudaMemcpyHostToDevice) !=
                    cudaSuccess) {
                    err = "cudaMemcpy failed for " + r.name;
                    free_staging(stage_in); free_staging(stage_out);
                    return false;
                }
                upload_ms += now_ms() - u0;
                done += n;
            }
        }

        WeightRef wr;
        wr.data = dst_base + r.dst_off;
        wr.bytes = r.dst_bytes;
        wr.ne0 = r.ne0;
        wr.ne1 = r.ne1;
        wr.elements = r.ne0 * (r.ne1 > 0 ? r.ne1 : 1);
        wr.kind = r.kind;
        wr.code_bits = r.code_bits;
        wr.code_bias = r.code_bias;
        wr.group_elems = r.group_elems;
        wr.codebook_iq4nl = r.codebook != 0;
        wr.has_offset = r.has_offset != 0;
        wr.codes_bytes = r.codes_bytes;
        wr.scales_bytes = r.scales_bytes;
        wr.offset_bytes = r.offset_bytes;
        wr.src_off = r.src_off;
        wr.src_bytes = r.src_bytes;
        wr.file_id = r.file;
        wr.scales_fp16 = r.scales_fp16 != 0;
        wr.act_kind = r.act_kind;
        table_[r.name] = wr;

        ++report_.tensors;
        if ((r.kind == WeightKind::Bf16InF32 || r.kind == WeightKind::F16InF32) && !r.raw16) {
            ++report_.re_rounded;
            report_.bytes_saved += r.src_bytes - r.dst_bytes;
        }
    }
    current_file.reset();
    const auto input_release = free_staging(stage_in);
    const auto output_release = free_staging(stage_out);
    if (input_release != cudaSuccess || output_release != cudaSuccess) {
        err = "weight table: staging release incomplete; memory claims retained";
        return false;
    }

    report_.arena_bytes = pool;
    report_.read_ms = now_ms() - t_read0 - upload_ms;
    report_.upload_ms = upload_ms;
    if (cudaDeviceSynchronize() != cudaSuccess) { err = "cudaDeviceSynchronize after the load failed"; return false; }
    return true;
}

const WeightRef* WeightTable::find(const std::string& name) const {
    const auto it = table_.find(name);
    if(it!=table_.end() && it->second.native_revoked)return nullptr;
    if(it!=table_.end() && it->second.native_data) {
        auto owner=it->second.native_owner.lock();
        if(!owner || owner->quarantined.load())return nullptr;
    }
    return it == table_.end() ? nullptr : &it->second;
}

bool WeightTable::pin_native_weights(std::vector<std::shared_ptr<NativeWeightStorage>>& owners,std::string& err) const {
    std::set<NativeWeightStorage*> seen;
    std::vector<std::shared_ptr<NativeWeightStorage>> pending;
    for(const auto& owner:owners) {
        if(!owner || owner->quarantined.load()){err="native weights: retained owner unavailable";return false;}
        seen.insert(owner.get());
    }
    for(const auto& item:table_) {
        if(item.second.native_revoked){err="native weights: table binding revoked";return false;}
        if(!item.second.native_data)continue;
        auto owner=item.second.native_owner.lock();
        if(!owner || owner->quarantined.load()){err="native weights: backing owner unavailable";return false;}
        if(seen.insert(owner.get()).second)pending.push_back(std::move(owner));
    }
    owners.reserve(owners.size()+pending.size());
    for(auto& owner:pending)owners.push_back(std::move(owner));
    return true;
}

}  // namespace strata::core
