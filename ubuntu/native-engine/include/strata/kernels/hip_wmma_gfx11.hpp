#pragma once
// Adapt the engine's gfx12 logical fragments to gfx11 replicated inputs and
// interleaved FP32 accumulators. Keep this opt-in until engine parity passes.
// Layout reference: AMD ROCm Optimization Guide, RDNA3 dense WMMA builtins.
#if defined(__HIPCC__)
#include <hip/hip_runtime.h>
namespace strata::kernels::gfx11 {
using H8 = _Float16 __attribute__((ext_vector_type(8)));
using H16 = _Float16 __attribute__((ext_vector_type(16)));
using S8 = short __attribute__((ext_vector_type(8)));
using S16 = short __attribute__((ext_vector_type(16)));
using F8 = float __attribute__((ext_vector_type(8)));

__device__ __forceinline__ F8 interleave(F8 c) {
    F8 r;
    const int lane = threadIdx.x & 31, col = lane & 15, half = lane >> 4;
#pragma unroll
    for (int i = 0; i < 8; ++i) {
        const int src = col + (i >= 4 ? 16 : 0);
        const float even = __shfl(c[(2*i)&7],src,32);
        const float odd = __shfl(c[(2*i+1)&7],src,32);
        r[i] = half ? odd : even;
    }
    return r;
}
__device__ __forceinline__ F8 contiguous(F8 c) {
    F8 r;
    const int lane = threadIdx.x & 31, col = lane & 15, half = lane >> 4;
#pragma unroll
    for (int i = 0; i < 8; ++i) {
        const int src = col + ((i & 1) ? 16 : 0);
        const float lower = __shfl(c[i>>1],src,32);
        const float upper = __shfl(c[4+(i>>1)],src,32);
        r[i] = half ? upper : lower;
    }
    return r;
}
__device__ __forceinline__ H16 replicate(H8 x) {
    H16 r;
    const int col = threadIdx.x & 15;
#pragma unroll
    for (int i = 0; i < 16; ++i) {
        union { _Float16 h; unsigned short u; } bits;
        bits.h = x[i & 7];
        bits.u = (unsigned short)__shfl((unsigned)bits.u, col + (i >= 8 ? 16 : 0), 32);
        r[i] = bits.h;
    }
    return r;
}
__device__ __forceinline__ S16 replicate(S8 x) {
    S16 r;
    const int col = threadIdx.x & 15;
#pragma unroll
    for (int i = 0; i < 16; ++i) r[i] = (short)__shfl((int)x[i & 7],col+(i>=8?16:0),32);
    return r;
}
__device__ __forceinline__ F8 f16(H8 a, H8 b, F8 c) {
#if defined(__gfx1100__) || defined(__gfx1101__) || defined(__gfx1102__) || defined(__gfx1103__)
    return contiguous(__builtin_amdgcn_wmma_f32_16x16x16_f16_w32(replicate(a),replicate(b),interleave(c)));
#else
    __builtin_trap(); return c;
#endif
}
__device__ __forceinline__ F8 bf16(S8 a, S8 b, F8 c) {
#if defined(__gfx1100__) || defined(__gfx1101__) || defined(__gfx1102__) || defined(__gfx1103__)
    return contiguous(__builtin_amdgcn_wmma_f32_16x16x16_bf16_w32(replicate(a),replicate(b),interleave(c)));
#else
    __builtin_trap(); return c;
#endif
}
}
#endif
