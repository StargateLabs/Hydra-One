// src/core/expert_cache.cpp - R4's slot storage and residency table.  Read the header first.
#include "hydra/core/expert_cache.hpp"

#include <cuda_runtime.h>
#include "hydra/core/budget_allocator.hpp"

#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <utility>
#include <cstring>
#include <limits>
#include <set>

namespace strata::core {

bool read_expert_profile(const std::string& path, int64_t n_layers, int64_t n_expert,
                         std::vector<std::pair<int32_t, int32_t>>& ranked, int64_t& slots, std::string& err) {
    std::FILE* f = std::fopen(path.c_str(), "rb");
    if (f == nullptr) {
        err = "read_expert_profile: cannot open " + path;
        return false;
    }
    char magic[4] = {0, 0, 0, 0};
    uint32_t hdr[5] = {0, 0, 0, 0, 0};
    if (std::fread(magic, 1, 4, f) != 4 || std::fread(hdr, 4, 5, f) != 5) {
        std::fclose(f);
        err = "read_expert_profile: " + path + " is too short to hold a header";
        return false;
    }
    if (std::memcmp(magic, "STRP", 4) != 0) {
        std::fclose(f);
        err = "read_expert_profile: " + path + " does not start with STRP";
        return false;
    }
    const uint32_t version = hdr[0], nl = hdr[1], ne = hdr[2], want = hdr[3], n_ranked = hdr[4];
    if ((int64_t) nl != n_layers || (int64_t) ne != n_expert) {
        std::fclose(f);
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "read_expert_profile: %s is %ux%u but this model is %lldx%lld - it is a profile for a "
                      "different artifact", path.c_str(), nl, ne, (long long) n_layers, (long long) n_expert);
        err = buf;
        return false;
    }
    if (n_ranked > want) {
        std::fclose(f);
        err = "read_expert_profile: the header claims more ranked pairs than slots";
        return false;
    }
    // Reject incompatible formats and impossible payloads before allocating.
    std::error_code size_error;
    const auto file_bytes = std::filesystem::file_size(path, size_error);
    const uint64_t cells = uint64_t(nl) * uint64_t(ne);
    if (version != 1 || !nl || !ne || nl > 65535 || ne > 65535 ||
        n_ranked > cells || want > cells || size_error ||
        file_bytes != 24ull + 4ull * n_ranked + 4ull * cells) {
        std::fclose(f);
        err = "read_expert_profile: unsupported version/layout or invalid payload size";
        return false;
    }
    std::vector<std::pair<int32_t, int32_t>> admitted(n_ranked);
    std::set<std::pair<int32_t, int32_t>> unique;
    std::vector<uint16_t> raw((size_t) n_ranked * 2);
    if (n_ranked > 0 && std::fread(raw.data(), 2, (size_t) n_ranked * 2, f) != (size_t) n_ranked * 2) {
        std::fclose(f);
        err = "read_expert_profile: the ranked list is truncated";
        return false;
    }
    std::fclose(f);
    for (uint32_t i = 0; i < n_ranked; ++i) {
        const int32_t l = (int32_t) raw[(size_t) i * 2], e = (int32_t) raw[(size_t) i * 2 + 1];
        if (l < 0 || l >= n_layers || e < 0 || e >= n_expert) {
            char buf[256];
            std::snprintf(buf, sizeof buf, "read_expert_profile: pair %u is (layer %d, expert %d), out of range",
                          i, l, e);
            err = buf;
            return false;
        }
        if (!unique.emplace(l, e).second) {
            err = "read_expert_profile: duplicate ranked pair";
            return false;
        }
        admitted[(size_t) i] = {l, e};
    }
    ranked.swap(admitted);
    slots = (int64_t) want;
    (void) version;   // a future format bumps it; the layout check above is what protects this reader today
    return true;
}

std::vector<std::pair<int32_t, int32_t>> rank_learned_profile(int64_t n_layers, int64_t n_expert,
                                                              const std::vector<uint8_t>& resident,
                                                              const std::vector<double>& heat,
                                                              const std::vector<std::pair<int32_t, int32_t>>& prior) {
    const size_t n = (size_t) (n_layers * n_expert);
    std::vector<int64_t> prior_rank(n, INT64_MAX);
    for (size_t r = 0; r < prior.size(); ++r) {
        const auto [l, e] = prior[r];
        if (l >= 0 && l < n_layers && e >= 0 && e < n_expert) {
            int64_t& pr = prior_rank[(size_t) (l * n_expert + e)];
            if (pr == INT64_MAX) pr = (int64_t) r;
        }
    }
    std::vector<int64_t> order(n);
    for (size_t i = 0; i < n; ++i) order[i] = (int64_t) i;
    auto res = [&](int64_t i) { return (size_t) i < resident.size() && resident[(size_t) i] != 0; };
    auto ht = [&](int64_t i) { return (size_t) i < heat.size() ? heat[(size_t) i] : 0.0; };
    std::stable_sort(order.begin(), order.end(), [&](int64_t a, int64_t b) {
        if (res(a) != res(b)) return res(a);
        if (ht(a) != ht(b)) return ht(a) > ht(b);
        if (prior_rank[(size_t) a] != prior_rank[(size_t) b]) return prior_rank[(size_t) a] < prior_rank[(size_t) b];
        return a < b;
    });
    std::vector<std::pair<int32_t, int32_t>> ranked(n);
    for (size_t r = 0; r < n; ++r)
        ranked[r] = {(int32_t) (order[r] / n_expert), (int32_t) (order[r] % n_expert)};
    return ranked;
}

bool write_expert_profile(const std::string& path, int64_t n_layers, int64_t n_expert,
                          const std::vector<std::pair<int32_t, int32_t>>& ranked, std::string& err) {
    if (n_layers <= 0 || n_expert <= 0 || n_layers > 65535 || n_expert > 65535) {
        err = "write_expert_profile: the model's layout does not fit the format";
        return false;
    }
    std::vector<int32_t> table((size_t) (n_layers * n_expert), -1);
    std::vector<uint16_t> pairs;
    if (ranked.size() > table.size()) {err = "write_expert_profile: too many ranked pairs";return false;}
    pairs.reserve(ranked.size() * 2);
    for (size_t r = 0; r < ranked.size(); ++r) {
        const auto [l, e] = ranked[r];
        if (l < 0 || l >= n_layers || e < 0 || e >= n_expert) {
            err = "write_expert_profile: a ranked pair is out of range";
            return false;
        }
        if (table[(size_t) (l * n_expert + e)] != -1) {
            err = "write_expert_profile: duplicate ranked pair";
            return false;
        }
        table[(size_t) (l * n_expert + e)] = (int32_t) r;
        pairs.push_back((uint16_t) l);
        pairs.push_back((uint16_t) e);
    }
    const uint32_t hdr[5] = {1u, (uint32_t) n_layers, (uint32_t) n_expert, (uint32_t) ranked.size(),
                             (uint32_t) ranked.size()};
    const std::string tmp = path + ".tmp";
    std::FILE* f = std::fopen(tmp.c_str(), "wb");
    if (f == nullptr) {
        err = "write_expert_profile: cannot create " + tmp;
        return false;
    }
    // the format is little-endian (make_profile.py's "<"): so is every machine this engine runs on
    bool ok = std::fwrite("STRP", 1, 4, f) == 4 && std::fwrite(hdr, 4, 5, f) == 5 &&
              (pairs.empty() || std::fwrite(pairs.data(), 2, pairs.size(), f) == pairs.size()) &&
              std::fwrite(table.data(), 4, table.size(), f) == table.size();
    ok = (std::fclose(f) == 0) && ok;
    std::error_code ec;
    if (ok) std::filesystem::rename(tmp, path, ec);   // replaces an existing file (MoveFileEx / rename(2))
    if (!ok || ec) {
        std::filesystem::remove(tmp, ec);
        err = "write_expert_profile: cannot write " + path;
        return false;
    }
    return true;
}

ExpertCache::~ExpertCache() { close(); }

#if defined(STRATA_USE_HIP)
bool ExpertCache::ensure_blocking_staging(std::size_t bytes, std::string& err) {
    if (bytes <= blocking_staging_bytes_) return true;
    void* next = nullptr;
    const cudaError_t status = ::strata::core::budget_for(::strata::core::BudgetComponent::Staging).host_alloc(&next, bytes, cudaHostAllocDefault);
    if (status != cudaSuccess) {
        err = std::string("ExpertCache: HIP blocking staging allocation: ") + cudaGetErrorString(status);
        return false;
    }
    if (blocking_staging_ && ::strata::core::budget_host_free(blocking_staging_)!=cudaSuccess) {
        // Preserve the current owner if its release cannot be attested.
        // A failed rollback of next remains charged in the native ledger.
        (void) ::strata::core::budget_host_free(next);
        err="ExpertCache: previous HIP staging release unverified";
        return false;
    }
    blocking_staging_ = static_cast<uint8_t*>(next);
    blocking_staging_bytes_ = bytes;
    return true;
}
#endif

bool ExpertCache::open(int64_t n_slots, int64_t n_layers, int64_t n_expert, int64_t blob_bytes,
                       std::string& err) {
    return open_storage(n_slots,n_layers,n_expert,blob_bytes,err,n_slots,blob_bytes);
}

bool ExpertCache::open_storage(int64_t n_slots,int64_t n_layers,int64_t n_expert,int64_t blob_bytes,
                              std::string& err,int64_t ownership_slots,int64_t staging_bytes) {
    close();
    if (base_ != nullptr || !close_error_.empty()) { err = "ExpertCache: previous ownership/completion not released"; return false; }
    if (n_slots <= 0 || ownership_slots<=0 || ownership_slots>INT32_MAX) {
        err = "ExpertCache: n_slots must be positive";
        return false;
    }
    if (n_layers <= 0 || n_expert <= 0 || blob_bytes <= 0) {
        err = "ExpertCache: n_layers, n_expert and blob_bytes must all be positive";
        return false;
    }

    if ((uint64_t)n_slots > (uint64_t)INT64_MAX/(uint64_t)blob_bytes ||
        (uint64_t)n_layers > (uint64_t)SIZE_MAX/sizeof(int32_t)/(uint64_t)n_expert) {
        err = "ExpertCache: arena/table size overflow"; return false;
    }
    const uint64_t want = (uint64_t) n_slots * (uint64_t) blob_bytes;

    // ---- **THE ALLOCATION IS CHECKED AGAINST THE CARD, NOT AGAINST THE REQUEST.**
    //
    // `cudaMalloc` failing is the easy case. The one that matters is a machine where the weights already own
    // most of VRAM: the cache then takes what is left and `slots()` would report the number ASKED FOR while
    // `device_slot()` walks off the end. So the free-VRAM figure is read and compared BEFORE the allocation,
    // and the two numbers are named in the refusal.
    size_t free_b = 0, total_b = 0;
    if (cudaMemGetInfo(&free_b, &total_b) != cudaSuccess || free_b > total_b) {
        err = "ExpertCache: current free VRAM is unavailable or inconsistent";
        return false;
    }
    {
        if ((uint64_t) free_b < want) {
            char buf[320];
            std::snprintf(buf, sizeof buf,
                          "ExpertCache: %lld slots x %lld B = %.2f GiB, but only %.2f GiB of VRAM is free "
                          "(%.2f GiB of %.2f GiB total). Lower --expert-cache.",
                          (long long) n_slots, (long long) blob_bytes, (double) want / 1073741824.0,
                          (double) free_b / 1073741824.0, (double) (total_b - free_b) / 1073741824.0,
                          (double) total_b / 1073741824.0);
            err = buf;
            return false;
        }
    }

    if (::strata::core::budget_for(::strata::core::BudgetComponent::ExpertCache).device_alloc((void**) &base_, (size_t) want) != cudaSuccess) {
        base_ = nullptr;
        char buf[256];
        std::snprintf(buf, sizeof buf, "ExpertCache: cudaMalloc(%.2f GiB) failed: %s",
                      (double) want / 1073741824.0, cudaGetErrorString(cudaGetLastError()));
        err = buf;
        return false;
    }
    // Zeroed so a slot read before it is filled is a DETERMINISTIC wrong answer rather than whatever the
    // allocator handed back.  A stale block of a previous process's memory would still sum to finite floats.
    if (cudaMemset(base_, 0, (size_t) want) != cudaSuccess) {
        err = "ExpertCache: cudaMemset of the slot arena failed";
        close();
        return false;
    }

    residency_.assign((size_t) (n_layers * n_expert), kNotResident);
    slots_ = n_slots;
    lifecycle_.reset((size_t)ownership_slots);
    pending_.assign((size_t)ownership_slots,false);
    replacement_target_.assign((size_t)ownership_slots,SIZE_MAX);
    pending_stream_.assign((size_t)ownership_slots,nullptr);
    n_layers_ = n_layers;
    n_expert_ = n_expert;
    blob_ = blob_bytes;
#if defined(STRATA_USE_HIP)
    if (!ensure_blocking_staging((std::size_t) staging_bytes, err)) {
        close();
        return false;
    }
#endif
    next_free_ = 0;
    fills_ = 0;
    admitted_ = 0;
    // R4.2g: each layer starts at the bottom of its own range.  Built here rather than lazily so `admit`
    // stays allocation-free on the token path.
    layer_next_.assign((size_t) (n_layers > 0 ? n_layers : 0), 0);
    for (int64_t l = 0; l < n_layers; ++l) {
        int64_t lo = 0, hi = 0;
        layer_slot_range(l, lo, hi);
        layer_next_[(size_t) l] = (int32_t) lo;
    }
    return true;
}

bool ExpertCache::open_sized(const std::vector<int64_t>& slot_bytes, int64_t n_layers, int64_t n_expert,
                             std::string& err) {
    if (slot_bytes.empty()) { err = "ExpertCache: no slots"; return false; }
    int64_t mx = 0;
    std::vector<uint64_t> off(slot_bytes.size() + 1, 0);
    for (size_t i = 0; i < slot_bytes.size(); ++i) {
        if (slot_bytes[i] <= 0 || (uint64_t)slot_bytes[i] > (uint64_t)std::numeric_limits<int64_t>::max()-255 || off[i] > (uint64_t)std::numeric_limits<int64_t>::max()-((uint64_t)slot_bytes[i]+255)) {
            err="ExpertCache: invalid/overflowing sized slot"; return false;
        }
        // 256-byte aligned slots, so every blob starts where the kernels' vector loads expect it
        off[i + 1] = off[i] + ((uint64_t) slot_bytes[i] + 255) / 256 * 256;
        mx = slot_bytes[i] > mx ? slot_bytes[i] : mx;
    }
    // Allocate the aligned sum without pretending every byte is an ownership slot.
    if (!open_storage(1,n_layers,n_expert,(int64_t)off.back(),err,(int64_t)slot_bytes.size(),mx)) return false;
    slots_ = (int64_t) slot_bytes.size();
    lifecycle_.reset(slot_bytes.size());
    pending_.assign(slot_bytes.size(),false);
    replacement_target_.assign(slot_bytes.size(),SIZE_MAX);
    pending_stream_.assign(slot_bytes.size(),nullptr);
    blob_ = mx;
    off_ = std::move(off);
    slot_bytes_ = slot_bytes;
#if defined(STRATA_USE_HIP)
    if (!ensure_blocking_staging((std::size_t) blob_, err)) {
        close();
        return false;
    }
#endif
    // #369: each layer's cursor at the bottom of its own range, as open() seeds it - open() above ran on byte-sized
    // "slots", so its seeds are not slot indices
    layer_next_.assign((size_t) (n_layers > 0 ? n_layers : 0), 0);
    for (int64_t l = 0; l < n_layers; ++l) {
        int64_t lo = 0, hi = 0;
        layer_slot_range(l, lo, hi);
        layer_next_[(size_t) l] = (int32_t) lo;
    }
    return true;
}

void ExpertCache::close() {
    std::string completion_error;
    for(size_t i=0;i<pending_.size();++i)if(lifecycle_.snapshot(i).pins){close_error_="ExpertCache: active host slot leases";return;}
    if (!drain(completion_error)) {close_error_=completion_error;return;}
    if (!lifecycle_.close()) {close_error_="ExpertCache: active host slot leases";return;}
    close_error_.clear();
    pending_.clear(); pending_stream_.clear(); replacement_target_.clear();
    tracked_replacement_=false;
#if defined(STRATA_USE_HIP)
    if (blocking_staging_ && ::strata::core::budget_host_free(blocking_staging_)!=cudaSuccess) {close_error_="ExpertCache: staging release failed";return;}
    blocking_staging_ = nullptr;
    blocking_staging_bytes_ = 0;
#endif
    if (base_ != nullptr) {
        if(::strata::core::budget_device_free(base_)!=cudaSuccess){close_error_="ExpertCache: arena release failed";return;}
        base_ = nullptr;
    }
    slot_bytes_.clear();off_.clear();
    residency_.clear();
    slots_ = 0;
    n_layers_ = 0;
    n_expert_ = 0;
    blob_ = 0;
    next_free_ = 0;
    fills_ = 0;
    admitted_ = 0;
    layer_next_.clear();
}

/// R4.2g.  Layer `l` owns `[l*q, (l+1)*q)` with `q = slots_ / n_layers_`; the LAST layer takes whatever is
/// left over, so the ranges always cover `0..slots_` exactly and no slot is orphaned by the division.
void ExpertCache::layer_slot_range(int64_t layer, int64_t& lo, int64_t& hi) const {
    lo = 0;
    hi = 0;
    if (n_layers_ <= 0 || slots_ <= 0 || layer < 0 || layer >= n_layers_) return;
    const int64_t q = slots_ / n_layers_;
    lo = layer * q;
    hi = (layer == n_layers_ - 1) ? slots_ : (layer + 1) * q;
}

int32_t ExpertCache::slot_of(int64_t layer, int64_t expert) const {
    if (layer < 0 || layer >= n_layers_ || expert < 0 || expert >= n_expert_) return kNotResident;
    return residency_[(size_t) (layer * n_expert_ + expert)];
}

int32_t ExpertCache::admit(int64_t layer, int64_t expert) {
    if (layer < 0 || layer >= n_layers_ || expert < 0 || expert >= n_expert_) return kNotResident;
    const size_t at = (size_t) (layer * n_expert_ + expert);
    if (residency_[at] != kNotResident) return residency_[at];
    // R4.2g: THE PER-LAYER PATH.  Same "no eviction" rule, but the ceiling is this layer's own range rather
    // than one counter shared by all 48 - which is what confined the measured hit rate to 2.97%.
    if (per_layer_) {
        if (layer_next_.empty()) return kNotResident;
        int64_t lo = 0, hi = 0;
        layer_slot_range(layer, lo, hi);
        if ((int64_t) layer_next_[(size_t) layer] >= hi) return kNotResident;   // this layer's quota is full
        residency_[at] = layer_next_[(size_t) layer]++;
        ++admitted_;
        return residency_[at];
    }
    if (next_free_ >= slots_) return kNotResident;   // full: no eviction, deliberately - see the header
    residency_[at] = (int32_t) next_free_;
    return (int32_t) next_free_++;
}

uint8_t* ExpertCache::device_slot(int32_t slot) {
    if (slot < 0 || slot >= slots_) return nullptr;
    if (!off_.empty()) return base_ + off_[(size_t) slot];
    return base_ + (size_t) slot * (size_t) blob_;
}

const uint8_t* ExpertCache::device_slot(int32_t slot) const {
    if (slot < 0 || slot >= slots_) return nullptr;
    if (!off_.empty()) return base_ + off_[(size_t) slot];
    return base_ + (size_t) slot * (size_t) blob_;
}

bool ExpertCache::fill_slot(int32_t slot, const uint8_t* host_blob, void* stream, std::string& err, int64_t bytes) {
    size_t n;
    if (!copy_size(slot, bytes, n, err)) return false;
    uint8_t* dst = device_slot(slot);
    if (dst == nullptr) {
        err = "ExpertCache::fill_slot: slot " + std::to_string(slot) + " is outside 0.." +
              std::to_string(slots_ - 1);
        return false;
    }
    if (host_blob == nullptr) {
        err = "ExpertCache::fill_slot: the host blob is null";
        return false;
    }
    if (lifecycle_.snapshot((size_t)slot).state != SlotLifecycle::State::Reserved || lifecycle_.snapshot((size_t)slot).pins || !complete_slot(slot,err) || !lifecycle_.begin_load((size_t)slot)) {err="ExpertCache: slot reuse requires revocable graph references; initial fill only";return false;}
    const cudaError_t e = cudaMemcpyAsync(dst, host_blob, n, cudaMemcpyHostToDevice,
                                          (cudaStream_t) stream);
    if (e != cudaSuccess) {
        lifecycle_.complete((size_t)slot,false);
        err = std::string("ExpertCache::fill_slot: ") + cudaGetErrorString(e);
        return false;
    }
    pending_[(size_t)slot]=true;pending_stream_[(size_t)slot]=stream;
    ++fills_;
    return true;
}

bool ExpertCache::fill_slot_blocking(int32_t slot, const uint8_t* host_blob, std::string& err, int64_t bytes) {
    size_t n;
    if (!copy_size(slot, bytes, n, err)) return false;
    uint8_t* dst = device_slot(slot);
    if (dst == nullptr) {
        err = "ExpertCache::fill_slot_blocking: slot outside the arena";
        return false;
    }
    if (host_blob == nullptr) {
        err = "ExpertCache::fill_slot_blocking: the host blob is null";
        return false;
    }
    if (lifecycle_.snapshot((size_t)slot).state != SlotLifecycle::State::Reserved || lifecycle_.snapshot((size_t)slot).pins || !complete_slot(slot,err) || !lifecycle_.begin_load((size_t)slot)) {err="ExpertCache: slot reuse requires revocable graph references; initial fill only";return false;}
#if defined(STRATA_USE_HIP)
    // Bound HIP's pageable-source staging to one expert instead of repeatedly
    // registering regions of the mmap. The blocking copy completes before reuse.
    if (!blocking_staging_ || n > blocking_staging_bytes_) {
        lifecycle_.complete((size_t)slot,false);
        err = "ExpertCache::fill_slot_blocking: HIP staging buffer is too small";
        return false;
    }
    std::memcpy(blocking_staging_, host_blob, n);
    const cudaError_t e = cudaMemcpy(dst, blocking_staging_, n, cudaMemcpyHostToDevice);
#else
    const cudaError_t e = cudaMemcpy(dst, host_blob, n, cudaMemcpyHostToDevice);
#endif
    if (e != cudaSuccess) {
        lifecycle_.complete((size_t)slot,false);
        err = std::string("ExpertCache::fill_slot_blocking: ") + cudaGetErrorString(e);
        return false;
    }
    lifecycle_.complete((size_t)slot,true);
    ++fills_;
    return true;
}

bool ExpertCache::fill_slot_queued(int32_t slot, const uint8_t* host_blob, std::string& err, int64_t bytes) {
    size_t n;
    if (!copy_size(slot, bytes, n, err)) return false;
    uint8_t* dst = device_slot(slot);
    if (dst == nullptr || host_blob == nullptr) {
        err = dst == nullptr ? "ExpertCache::fill_slot_queued: slot outside the arena"
                             : "ExpertCache::fill_slot_queued: the host blob is null";
        return false;
    }
    if (lifecycle_.snapshot((size_t)slot).state != SlotLifecycle::State::Reserved || lifecycle_.snapshot((size_t)slot).pins || !complete_slot(slot,err) || !lifecycle_.begin_load((size_t)slot)) {err="ExpertCache: slot reuse requires revocable graph references; initial fill only";return false;}
    const cudaError_t e = cudaMemcpyAsync(dst, host_blob, n, cudaMemcpyHostToDevice, (cudaStream_t) 0);
    if (e != cudaSuccess) {
        lifecycle_.complete((size_t)slot,false);
        err = std::string("ExpertCache::fill_slot_queued: ") + cudaGetErrorString(e);
        return false;
    }
    pending_[(size_t)slot]=true;pending_stream_[(size_t)slot]=nullptr;
    ++fills_;
    return true;
}

bool ExpertCache::sync_queued(std::string& err) {
    const cudaError_t e = cudaStreamSynchronize((cudaStream_t) 0);
    if (e != cudaSuccess) {
        err = std::string("ExpertCache::sync_queued: ") + cudaGetErrorString(e);
        return false;
    }
    for(size_t i=0;i<pending_.size();++i)if(pending_[i]&&pending_stream_[i]==nullptr&&!finish_copy((int32_t)i,err))return false;
    return true;
}

bool ExpertCache::verify_slot(int32_t slot, const uint8_t* host_blob, std::string& err, int64_t bytes) {
    size_t count;
    if (!copy_size(slot, bytes, count, err) || host_blob == nullptr) { err="ExpertCache::verify_slot: invalid size/host"; return false; }
    if (!complete_slot(slot,err)) return false;
    const int64_t nb = (int64_t) count;
    const uint8_t* src = device_slot(slot);
    if (src == nullptr) {
        err = "ExpertCache::verify_slot: slot outside the arena";
        return false;
    }
    // `cudaMemcpy` and not `cudaMemcpyAsync`: this is a startup check, and a check that can be read before it
    // has happened is not a check.  It also synchronises the fills queued before it, which is what makes the
    // comparison meaningful.
    std::vector<uint8_t> got((size_t) nb);
    const cudaError_t e = cudaMemcpy(got.data(), src, (size_t) nb, cudaMemcpyDeviceToHost);
    if (e != cudaSuccess) {
        err = std::string("ExpertCache::verify_slot: ") + cudaGetErrorString(e);
        return false;
    }
    if (std::memcmp(got.data(), host_blob, (size_t) nb) != 0) {
        size_t first = 0;
        while (first < (size_t) nb && got[first] == host_blob[first]) ++first;
        char buf[256];
        std::snprintf(buf, sizeof buf,
                      "ExpertCache::verify_slot: slot %d differs from the arena at byte %llu (of %lld)",
                      (int) slot, (unsigned long long) first, (long long) blob_);
        err = buf;
        return false;
    }
    return true;
}

bool ExpertCache::complete_slot(int32_t slot,std::string& err) const {
    if(slot<0||(size_t)slot>=pending_.size()){err="ExpertCache: invalid completion slot";return false;}
    if(!pending_[(size_t)slot])return true;
    const auto result=cudaStreamSynchronize((cudaStream_t)pending_stream_[(size_t)slot]);
    if(result!=cudaSuccess){err=std::string("ExpertCache: completion unknown: ")+cudaGetErrorString(result);return false;}
    return finish_copy(slot,err);
}

bool ExpertCache::finish_copy(int32_t slot,std::string& err) const {
    if(!lifecycle_.complete((size_t)slot,true)){err="ExpertCache: copy completion ownership mismatch";return false;}
    pending_[(size_t)slot]=false;
    auto& target=replacement_target_[(size_t)slot];
    if(target!=SIZE_MAX){residency_[target]=slot;target=SIZE_MAX;}
    return true;
}

bool ExpertCache::replace_slot(int32_t slot,int64_t layer,int64_t expert,const uint8_t* blob,
                                void* stream,int64_t bytes,std::string& err) {
    size_t count;
    if(!tracked_replacement_){err="ExpertCache: consumer has untracked references";return false;}
    if(!blob || layer<0 || layer>=n_layers_ || expert<0 || expert>=n_expert_ ||
       !copy_size(slot,bytes,count,err)){if(err.empty())err="ExpertCache: invalid replacement";return false;}
    const size_t target=(size_t)(layer*n_expert_+expert);
    if(residency_[target]!=kNotResident){err="ExpertCache: replacement already resident";return false;}
    if(!complete_slot(slot,err) || !lifecycle_.begin_replace((size_t)slot)) {
        if(err.empty())err="ExpertCache: replacement blocked by a pin or in-flight operation";
        return false;
    }
    // Old handles are invalid now; no lookup may publish the incoming expert yet.
    for(auto& resident:residency_)if(resident==slot)resident=kNotResident;
    replacement_target_[(size_t)slot]=target;
    const auto result=cudaMemcpyAsync(device_slot(slot),blob,count,cudaMemcpyHostToDevice,(cudaStream_t)stream);
    if(result!=cudaSuccess) {
        lifecycle_.complete((size_t)slot,false);
        replacement_target_[(size_t)slot]=SIZE_MAX;
        err=std::string("ExpertCache: replacement copy failed: ")+cudaGetErrorString(result);
        return false;
    }
    pending_stream_[(size_t)slot]=stream;pending_[(size_t)slot]=true;
    ++fills_;
    return true;
}

SlotLifecycle::Lease ExpertCache::acquire(int32_t slot,std::string& err) const {
    if(!complete_slot(slot,err))return {};
    auto lease=lifecycle_.pin((size_t)slot);
    if(!lease.valid())err="ExpertCache: slot not resident or failed";
    return lease;
}

bool ExpertCache::pin_graph_residency(std::vector<SlotLifecycle::Lease>& leases,std::string& err) const {
    if(!base_){err="ExpertCache: graph arena unavailable";return false;}
    std::vector<SlotLifecycle::Lease> pending;
    std::set<int32_t> seen;
    for(const auto& lease:leases) {
        if(!lifecycle_.owns(lease)||!lease.valid()||lease.slot()>=(size_t)slots_) {
            err="ExpertCache: stale or foreign graph lease";return false;
        }
        seen.insert((int32_t)lease.slot());
    }
    for(int32_t slot:residency_) {
        if(slot==kNotResident||!seen.insert(slot).second)continue;
        auto lease=acquire(slot,err);
        if(!lease.valid())return false;
        pending.push_back(std::move(lease));
    }
    leases.reserve(leases.size()+pending.size());
    for(auto& lease:pending)leases.push_back(std::move(lease));
    return true;
}

const uint8_t* ExpertCache::resolve(const SlotLifecycle::Lease& lease) const {
    if (!lifecycle_.owns(lease) || !lease.valid() || lease.slot() >= (size_t)slots_) return nullptr;
    return device_slot((int32_t)lease.slot());
}

const uint8_t* ExpertCache::resolve_slot(int32_t slot,const std::vector<SlotLifecycle::Lease>& leases) const {
    if(slot<0)return nullptr;
    for(const auto& lease:leases)if(lease.slot()==(size_t)slot)return resolve(lease);
    return nullptr;
}

SlotLifecycle::Lease ExpertCache::acquire_ordered(int32_t slot,void* stream,std::string& err) {
    if(slot<0||(size_t)slot>=pending_.size()||(pending_[(size_t)slot]&&pending_stream_[(size_t)slot]!=stream)) {err="ExpertCache: unknown cross-stream completion";return {};}
    auto lease=lifecycle_.pin((size_t)slot,pending_[(size_t)slot]);
    if(!lease.valid())err="ExpertCache: ordered slot unavailable";
    return lease;
}

bool ExpertCache::complete_ordered(int32_t slot,void* stream,std::string& err) {
    // Caller has queried the actual event recorded after this stream's kernel.
    if(slot<0||(size_t)slot>=pending_.size()||(pending_[(size_t)slot]&&pending_stream_[(size_t)slot]!=stream)){err="ExpertCache: completion stream mismatch";return false;}
    if(!pending_[(size_t)slot])return true;
    return finish_copy(slot,err);
}

bool ExpertCache::drain(std::string& err) {
    if(base_==nullptr)return true;
    // Also covers graph/legacy users that still retain raw arena addresses.
    const auto result=cudaDeviceSynchronize();
    if(result!=cudaSuccess){err=std::string("ExpertCache: shutdown completion unknown: ")+cudaGetErrorString(result);return false;}
    for(size_t i=0;i<pending_.size();++i)if(pending_[i]&&!finish_copy((int32_t)i,err))return false;
    return true;
}

bool ExpertCache::copy_size(int32_t slot, int64_t requested, size_t& bytes, std::string& err) const {
    if (slot < 0 || slot >= slots_ || requested < 0 || base_ == nullptr) {
        err = "ExpertCache: invalid slot/copy size"; return false;
    }
    const uint64_t capacity = slot_bytes_.empty() ? (uint64_t) blob_ : (uint64_t)slot_bytes_[(size_t)slot];
    const uint64_t count = requested == 0 ? capacity : (uint64_t) requested;
    if (count == 0 || count > capacity) { err="ExpertCache: copy exceeds this slot capacity"; return false; }
    bytes = (size_t) count; return true;
}

}  // namespace strata::core
