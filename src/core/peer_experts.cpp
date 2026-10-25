// src/core/peer_experts.cpp - see include/hydra/core/peer_experts.hpp.
#include "hydra/core/peer_experts.hpp"
#include "hydra/core/budget_allocator.hpp"
#include "hydra/core/checked_memory.hpp"

#include "hydra/kernels/cpu/expert_layout.hpp"
#include "hydra/kernels/elementwise.hpp"
#include "hydra/kernels/iq_kernels.hpp"
#include "hydra/kernels/quantize_act.hpp"
#include "hydra/kernels/s2_expert_grouped.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
#include <thread>
#include <set>

namespace strata::core {

static bool g_peer_portable = false;
void set_peer_portable(bool on) { g_peer_portable = on; }
bool peer_portable() { return g_peer_portable; }

namespace {

constexpr int64_t H = strata::kernels::cpu::H;
constexpr int64_t CAP = strata::kernels::cpu::MAXT * 10;   // entries per layer: MAXT tokens x top-10

struct Meta {                           // one block, uploaded with one copy per layer
    unsigned long long ptr[CAP];
    int32_t start[CAP + 1];
    int32_t dst[CAP];
    int32_t tok[CAP];
    int32_t count[4];                   // [0] groups, [1] entries
    int32_t out_row[CAP];               // multi-GPU: compact row -> entry row in the host `out`
};

/// Switches the calling thread to `dev` and back.  The engine's own thread lives on device 0.
struct On {
    int prev = -1;bool ok=false;
    explicit On(int dev) { if(cudaGetDevice(&prev)!=cudaSuccess)return;ok=prev==dev||cudaSetDevice(dev)==cudaSuccess; }
    ~On() { if(ok&&prev>=0)cudaSetDevice(prev); }
};

bool ck(cudaError_t e, const char* what, std::string& err) {
    if (e == cudaSuccess) return true;
    err = std::string("peer experts: ") + what + ": " + cudaGetErrorString(e);
    return false;
}

}  // namespace

PeerExperts::~PeerExperts() { close(); }

void PeerExperts::close() {
    std::lock_guard<std::mutex> lock(mutex_);
    close_locked();
}

void PeerExperts::close_locked() {
    if (device_ < 0) return;
    {
        On on(device_);
        if(!on.ok){failed_=true;return;}
        if ((stream_&&cudaStreamSynchronize(stream_)!=cudaSuccess)||(refill_&&cudaStreamSynchronize(refill_)!=cudaSuccess)) {failed_=true;return;}
        for(auto& lease:active_leases_)if(!lease.complete_operation()){failed_=true;return;}
        active_leases_.clear();
        cache_.close();
        if(cache_.valid()){failed_=true;return;}
        bool released=true;
        auto release=[&](auto& pointer,auto destroy){
            if(!pointer)return;
            if(destroy(pointer)!=cudaSuccess){released=false;return;}
            pointer=nullptr;
        };
        release(d_x_,::strata::core::budget_device_free);
        release(d_out_,::strata::core::budget_device_free);
        release(d_meta_,::strata::core::budget_device_free);
        release(d_q8_,::strata::core::budget_device_free);
        release(d_scratch_,::strata::core::budget_device_free);
        release(h_x_,::strata::core::budget_host_free);
        release(h_out_,::strata::core::budget_host_free);
        release(h_meta_,::strata::core::budget_host_free);
        release(refill_ev_,cudaEventDestroy);
        release(stream_,cudaStreamDestroy);
        release(refill_,cudaStreamDestroy);
        if(!released){failed_=true;return;}
    }
    d_x_ = d_out_ = h_x_ = h_out_ = nullptr;
    d_meta_ = h_meta_ = d_scratch_ = nullptr;
    d_q8_ = nullptr;
    stream_ = refill_ = nullptr;
    refill_ev_ = nullptr;
    device_ = -1;
    failed_ = false;
}

bool PeerExperts::open(int device, const std::vector<std::pair<int32_t, int32_t>>& ranked, const ExpertCache& primary,
                       ExpertSource& src, int64_t n_layers, int64_t n_expert, int reserve_mib, int64_t max_slots,
                       std::string& err) {
    std::lock_guard<std::mutex> lock(mutex_);
    close_locked();
    if(device_>=0){err="peer experts: previous cleanup incomplete";return false;}
    int count = 0;
    if (!ck(cudaGetDeviceCount(&count), "cudaGetDeviceCount", err)) return false;
    if (device < 1 || device >= count) {
        err = "peer experts: CUDA device " + std::to_string(device) + " is not visible (" + std::to_string(count) +
              " devices; set CUDA_VISIBLE_DEVICES)";
        return false;
    }
    const auto& lay = strata::kernels::cpu::expert_layout();
    uint64_t entries=0, table_bytes=0;
    if(n_layers<=0||n_expert<=0||n_expert!=lay.n_expert||
       (lay.n_layers>0&&n_layers!=lay.n_layers)||
       !checked_memory_mul(uint64_t(n_layers),uint64_t(n_expert),entries)||
       !checked_memory_mul(entries,sizeof(int32_t),table_bytes)){
        err="peer experts: invalid residency geometry";return false;
    }
    int64_t ff = strata::kernels::cpu::FF;
    if(lay.native){
        if(lay.fmt.size()!=size_t(n_layers)){err="peer experts: incomplete native geometry";return false;}
        for(const auto& f:lay.fmt){
            if(f.n_embd!=H||f.n_ff<=0||f.n_ff%32){err="peer experts: unsupported native geometry";return false;}
            ff=std::max<int64_t>(ff,f.n_ff);
        }
    }
    // Bound all products and alignment additions in both scratch implementations
    // before calling their unchecked size expressions. This is an upper bound,
    // not a change to either kernel's layout.
    uint64_t scratch_bound=0;
    if(!checked_memory_mul(uint64_t(CAP),uint64_t(ff),scratch_bound)||
       !checked_memory_mul(scratch_bound,32,scratch_bound)||
       !checked_memory_add(scratch_bound,4096,scratch_bound)){
        err="peer experts: scratch extent overflow";return false;
    }
    for(const auto& pr:ranked)if(pr.first<0||pr.first>=n_layers||pr.second<0||pr.second>=n_expert){
        err="peer experts: ranked expert outside layout";return false;
    }
    n_layers_ = n_layers;
    n_expert_ = n_expert;
    src_ = &src;
    res_.assign(size_t(entries), kNotResident);
    {   // direct access both ways (NVLink or another P2P path): the prompt path copies activations and results over it
        int a = 0, b = 0;
        cudaDeviceCanAccessPeer(&a, 0, device);
        cudaDeviceCanAccessPeer(&b, device, 0);
        p2p_ = a && b;
        if (p2p_) {
            On on0(0);
            cudaError_t e0 = cudaDeviceEnablePeerAccess(device, 0);
            if (e0 == cudaErrorPeerAccessAlreadyEnabled) { cudaGetLastError(); e0 = cudaSuccess; }
            On on1(device);
            cudaError_t e1 = cudaDeviceEnablePeerAccess(0, 0);
            if (e1 == cudaErrorPeerAccessAlreadyEnabled) { cudaGetLastError(); e1 = cudaSuccess; }
            p2p_ = e0 == cudaSuccess && e1 == cudaSuccess;
        }
    }
    On on(device);
    if(!on.ok){err="peer experts: device selection failed";return false;}
    device_ = device;
    // scratch first, so the slots take what is really left
    const size_t scratch = std::max<size_t>((size_t) strata::kernels::moe_hit_grouped_scratch_bytes(CAP, H, ff),
                                            strata::kernels::native_expert_scratch_bytes(CAP, ff));
    const bool alloc_ok =
        ck(cudaStreamCreateWithFlags(&stream_, cudaStreamNonBlocking), "stream", err) &&
        ck(cudaStreamCreateWithFlags(&refill_, cudaStreamNonBlocking), "refill stream", err) &&
        ck(cudaEventCreateWithFlags(&refill_ev_, cudaEventDisableTiming), "event", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::Staging).host_alloc((void**) &h_x_, (size_t) CAP * H * sizeof(float), cudaHostAllocPortable | cudaHostAllocMapped), "input staging", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::Staging).host_alloc((void**) &h_out_, (size_t) CAP * H * sizeof(float), cudaHostAllocPortable | cudaHostAllocMapped), "result staging", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::Staging).host_alloc(&h_meta_, sizeof(Meta), cudaHostAllocPortable | cudaHostAllocMapped), "plan staging", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::RuntimeBuffers).device_alloc((void**) &d_x_, (size_t) CAP * H * sizeof(float)), "input", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::RuntimeBuffers).device_alloc((void**) &d_out_, (size_t) CAP * H * sizeof(float)), "result", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::RuntimeBuffers).device_alloc(&d_meta_, sizeof(Meta)), "plan", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::RuntimeBuffers).device_alloc((void**) &d_q8_, (size_t) CAP * (H / 32) * 36), "activations", err) &&
        ck(::strata::core::budget_for(::strata::core::BudgetComponent::RuntimeBuffers).device_alloc(&d_scratch_, scratch), "scratch", err);
    if (!alloc_ok) { close_locked(); return false; }

    // the pairs the primary does not hold, in rank order, as many as fit
    size_t free_b = 0, total_b = 0;
    if (!ck(cudaMemGetInfo(&free_b, &total_b), "cudaMemGetInfo", err)) { close_locked(); return false; }
    const uint64_t reserve = (uint64_t) std::max(reserve_mib, 128) << 20;
    const uint64_t budget = free_b > reserve ? free_b - reserve : 0;
    std::vector<std::pair<int32_t, int32_t>> pick;
    std::vector<int64_t> sizes;
    uint64_t used = 0;
    std::set<std::pair<int32_t,int32_t>> selected;
    for (const auto& pr : ranked) {
        if(!selected.insert(pr).second)continue;
        if (primary.slot_of(pr.first, pr.second) >= 0) continue;
        const uint64_t b = lay.blob_bytes(pr.first);
        uint64_t padded=0;
        if(!b||!checked_memory_add(b,255,padded)||!lay.max_blob||lay.max_blob>kMemoryExtentMax){
            err="peer experts: invalid expert extent";close_locked();return false;
        }
        const uint64_t b256 = lay.native ? padded & ~uint64_t(255) : lay.max_blob;
        if (b256 > budget-used) break;
        if (max_slots > 0 && (int64_t) pick.size() >= max_slots) break;
        used += b256;
        pick.push_back(pr);
        sizes.push_back((int64_t) b);
    }
    if (pick.empty()) { err = "peer experts: no room or no expert left for the peer"; close_locked(); return false; }
    const bool opened = lay.native ? cache_.open_sized(sizes, n_layers, n_expert, err)
                                   : cache_.open((int64_t) pick.size(), n_layers, n_expert, (int64_t) lay.max_blob, err);
    if (!opened) { err = "peer experts: " + err; close_locked(); return false; }
    // open() zeroes the arena with cudaMemset on the legacy stream, which is not ordered against the non-blocking
    // refill stream: wait for it, or the zeroing can land on top of the fills
    if (!ck(cudaDeviceSynchronize(), "arena zeroing", err)) { close_locked(); return false; }
    for (const auto& pr : pick) {
        const int32_t slot = cache_.admit(pr.first, pr.second);
        const uint8_t* b = src.blob(pr.first, pr.second);
        if (slot < 0 || b == nullptr || !cache_.fill_slot(slot, b, refill_, err, (int64_t) lay.blob_bytes(pr.first))) {
            err = "peer experts: fill failed: " + err;
            close_locked();
            return false;
        }
        res_[(size_t) (pr.first * n_expert + pr.second)] = slot;
    }
    if (!ck(cudaStreamSynchronize(refill_), "fill", err)) { close_locked(); return false; }
    for(int32_t slot=0;slot<cache_.resident();++slot)if(!cache_.complete_ordered(slot,refill_,err)){close_locked();return false;}
    const auto& f0 = pick.front();
    if (!cache_.verify_slot(res_[(size_t) (f0.first * n_expert + f0.second)], src.blob(f0.first, f0.second), err,
                            (int64_t) lay.blob_bytes(f0.first))) {
        err = "peer experts: " + err;
        close_locked();
        return false;
    }
    resident_ = (int64_t) pick.size();
    cache_.tracked_replacement_=true;
    return true;
}

bool PeerExperts::launch(int64_t layer, const float* x, const int32_t* ids, int64_t n_tok, int64_t k,
                         const int32_t* kind, std::string& err, float* out) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(failed_||!active_leases_.empty()){err="peer experts: previous operation not completed";return false;}
    if(device_<0||layer<0||layer>=n_layers_||!x||!ids||!kind||n_tok<=0||n_tok>strata::kernels::cpu::MAXT||k!=10){err="peer experts: invalid routing geometry/pointers";return false;}
    for(int64_t i=0;i<n_tok*k;++i)if(ids[i]<0||ids[i]>=n_expert_){err="peer experts: invalid expert ID";return false;}
    static const bool direct_env = [] { const char* v = std::getenv("STRATA_PEER_DIRECT"); return v == nullptr || std::atoi(v) != 0; }();
    const bool direct = direct_env && out != nullptr;
    launched_direct_ = false;
    launched_rows_ = 0;
    row_of_.clear();
    const int64_t n = n_tok * k;
    if (n > CAP) { err = "peer experts: window too large"; return false; }
    Meta& m = *(Meta*) h_meta_;
    int groups = 0, rows = 0;
    // distinct experts in routing order; each one's entries become compact rows
    for (int64_t i = 0; i < n; ++i) {
        if (kind[i] != 2) continue;
        bool seen = false;
        for (int64_t j = 0; j < i; ++j)
            if (kind[j] == 2 && ids[j] == ids[i]) { seen = true; break; }
        if (seen) continue;
        const int32_t slot = res_[(size_t) (layer * n_expert_ + ids[i])];
        if (slot < 0) { err = "peer experts: an entry was planned for the peer but is not resident"; return false; }
        auto lease=cache_.acquire_ordered(slot,refill_,err);
        if(!lease.valid()){failed_=true;return false;}
        if(!lease.begin_operation()){failed_=true;err="peer experts: operation reservation refused";return false;}
        active_leases_.push_back(std::move(lease));
        const auto* address=cache_.resolve(active_leases_.back());
        if(!address){failed_=true;err="peer experts: stale or foreign slot handle";return false;}
        m.ptr[groups] = (unsigned long long) address;
        m.start[groups] = rows;
        for (int64_t j = i; j < n; ++j)
            if (kind[j] == 2 && ids[j] == ids[i]) {
                m.dst[rows] = rows;
                m.tok[rows] = (int32_t) (j / k);
                m.out_row[rows] = (int32_t) j;
                row_of_.push_back((int32_t) j);
                ++rows;
            }
        ++groups;
        ++experts_;
    }
    if (groups == 0) return true;
    m.start[groups] = rows;
    m.count[0] = groups;
    m.count[1] = rows;
    entries_ += rows;
    launched_rows_ = rows;
    // direct: x is the verifier's pinned (portable) doorbell row block - copied from where it is
    if (!direct) std::memcpy(h_x_, x, (size_t) (n_tok * H) * sizeof(float));
    On on(device_);
    if(!on.ok){failed_=true;err="peer experts: device selection failed";return false;}
    const cudaStream_t s = stream_;
    if (!ck(cudaMemcpyAsync(d_x_, direct ? x : h_x_, (size_t) (n_tok * H) * sizeof(float), cudaMemcpyHostToDevice, s), "input", err) ||
        !ck(cudaMemcpyAsync(d_meta_, h_meta_, sizeof(Meta), cudaMemcpyHostToDevice, s), "plan", err))
        return false;
    Meta* dm = (Meta*) d_meta_;
    const auto& lay = strata::kernels::cpu::expert_layout();
    if (lay.native) {
        strata::kernels::quantize_q8_1_rows(d_x_, n_tok, H, d_q8_, s);
        const auto& f = lay.fmt[(size_t) layer];
        const auto L = strata::kernels::native_expert_layout(f.gu_type, f.d_type, f.n_embd, f.n_ff);
        strata::kernels::native_expert_grouped(L, dm->ptr, dm->start, dm->count, dm->dst, dm->tok, groups, rows, d_q8_,
                                               d_scratch_, d_out_, s);
    } else {
        err = "peer experts: only native packs are supported";
        return false;
    }
    if (direct) {   // the rows straight into the host `out` (zero-copy, coalesced float4 writes)
        try {
            strata::kernels::scatter_rows_f32(d_out_, out, dm->out_row, rows, H, s);
        } catch (const std::exception& e) { err = std::string("peer experts: scatter: ") + e.what(); return false; }
        launched_direct_ = true;
        return true;
    }
    return ck(cudaMemcpyAsync(h_out_, d_out_, (size_t) rows * H * sizeof(float), cudaMemcpyDeviceToHost, s),
              "results", err);
}

bool PeerExperts::finish(float* out, std::string& err) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (launched_rows_ == 0) return true;
    if(!out&&!launched_direct_){failed_=true;err="peer experts: null destination";return false;}
    const auto t0 = std::chrono::steady_clock::now();
    {
        On on(device_);
        if(!on.ok){failed_=true;err="peer experts: device selection failed";return false;}
        // spin on the stream (a blocking sync would sleep the pool thread and wake it late)
        cudaError_t e;
        const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(30);
        while ((e = cudaStreamQuery(stream_)) == cudaErrorNotReady) {
            if(std::chrono::steady_clock::now()>=deadline){failed_=true;err="peer experts: completion timeout; leases retained";return false;}
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        if (!ck(e, "finish", err)) {failed_=true;return false;}
    }
    ms_wait += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
    for(auto& lease:active_leases_)if(!lease.complete_operation()){failed_=true;err="peer experts: completion ownership mismatch";return false;}
    active_leases_.clear();
    if (launched_direct_) { launched_rows_ = 0; return true; }
    for (size_t r = 0; r < row_of_.size(); ++r)
        std::memcpy(out + (size_t) row_of_[r] * H, h_out_ + r * H, (size_t) H * sizeof(float));
    launched_rows_ = 0;
    return true;
}

bool PeerExperts::adapt(const float* usage, const int32_t* res0, int max_swaps, std::string& err) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(max_swaps<=0)return true;
    if(failed_||device_<0||!usage||!res0||!src_||!active_leases_.empty()) {
        err="peer experts: adaptive replacement requires an idle valid owner";return false;
    }
    if(max_swaps>0&&!cache_.eviction_supported(err))return false;
    if (!pending_.empty() || max_swaps <= 0) return true;
    for(size_t i=0;i<res_.size();++i)if(!std::isfinite(usage[i])||usage[i]<0) {
        err="peer experts: invalid adaptive usage counter";return false;
    }
    const auto& lay = strata::kernels::cpu::expert_layout();
    struct Swap { float gain; int32_t layer, in, out; };
    std::vector<Swap> swaps;
    std::vector<std::pair<float, int32_t>> cand, vict;
    for (int64_t l = 0; l < n_layers_; ++l) {
        cand.clear();
        vict.clear();
        const float* u = usage + l * n_expert_;
        const int32_t* r0 = res0 + l * n_expert_;
        const int32_t* r1 = res_.data() + l * n_expert_;
        for (int32_t e = 0; e < (int32_t) n_expert_; ++e) {
            if (r1[e] >= 0) {
                const auto state=cache_.lifecycle_.snapshot((size_t)r1[e]);
                if(state.state==SlotLifecycle::State::Resident&&!state.pins&&!state.inflight)
                    vict.emplace_back(u[e],e);
            }
            else if (r0[e] < 0 && u[e] >= 2.0f) cand.emplace_back(u[e], e);
        }
        if (cand.empty() || vict.empty()) continue;
        std::sort(cand.begin(), cand.end(), [](auto& a, auto& b) { return a.first > b.first; });
        const size_t nc = std::min(cand.size(), vict.size());
        std::partial_sort(vict.begin(), vict.begin() + (ptrdiff_t) nc, vict.end(),
                          [](auto& a, auto& b) { return a.first < b.first; });
        for (size_t i = 0; i < nc; ++i) {
            if (cand[i].first < vict[i].first + 1.5f) break;
            swaps.push_back({cand[i].first - vict[i].first, (int32_t) l, cand[i].second, vict[i].second});
        }
    }
    if (swaps.empty()) return true;
    std::sort(swaps.begin(), swaps.end(), [](const Swap& a, const Swap& b) { return a.gain > b.gain; });
    if ((int) swaps.size() > max_swaps) swaps.resize((size_t) max_swaps);
    pending_.reserve(swaps.size()); // metadata cannot allocate after slot revocation
    On on(device_);
    if(!on.ok){failed_=true;err="peer experts: device selection failed";return false;}
    struct ReplacementGuard {
        bool& failed;
        bool committed=false;
        ~ReplacementGuard(){if(!committed)failed=true;}
    } replacement_guard{failed_};
    for (const Swap& s : swaps) {
        const size_t in = (size_t) (s.layer * n_expert_ + s.in), out = (size_t) (s.layer * n_expert_ + s.out);
        const int32_t slot = res_[out];
        const uint8_t* b = src_->blob(s.layer, s.in);
        if (slot < 0 || b == nullptr) continue;
        if(!cache_.replace_slot(slot,s.layer,s.in,b,refill_,(int64_t)lay.blob_bytes(s.layer),err)) {
            failed_=true;return false;
        }
        res_[out] = kNotResident;              // evicted now: the CPU computes it meanwhile
        pending_.emplace_back((int32_t) in, slot);
        ++swaps_;
    }
    if(!pending_.empty() && !ck(cudaEventRecord(refill_ev_,refill_),"refill event",err)){failed_=true;return false;}
    replacement_guard.committed=true;
    return true;
}

bool PeerExperts::pin_residency(std::vector<SlotLifecycle::Lease>& leases, std::string& err) {
    std::lock_guard<std::mutex> lock(mutex_);
    if(failed_ || device_<0){err="peer experts: unavailable owner";return false;}
    On on(device_);
    if(!on.ok){err="peer experts: device selection failed";return false;}
    apply_pending_locked(true);
    if(failed_){err="peer experts: pending replacement completion unknown";return false;}
    return cache_.pin_graph_residency(leases,err);
}

void PeerExperts::apply_pending(bool wait) {
    std::lock_guard<std::mutex> lock(mutex_);
    apply_pending_locked(wait);
}

void PeerExperts::apply_pending_locked(bool wait) {
    if(failed_)return;
    if (pending_.empty()) return;
    {
        On on(device_);
        if(!on.ok){failed_=true;return;}
        const auto result=wait?cudaEventSynchronize(refill_ev_):cudaEventQuery(refill_ev_);
        if(!wait && result==cudaErrorNotReady)return;
        if(result!=cudaSuccess){failed_=true;return;}
        std::string error;
        for(const auto& item:pending_)if(!cache_.complete_ordered(item.second,refill_,error)){failed_=true;return;}
    }
    for (const auto& [i, slot] : pending_) res_[(size_t) i] = slot;
    pending_.clear();
}

}  // namespace strata::core
