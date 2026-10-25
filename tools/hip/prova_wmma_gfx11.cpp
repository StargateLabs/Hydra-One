#include <hip/hip_runtime.h>
// Il kernel gfx12 del motore usa queste due (con suffisso _gfx12 e wave32).
// Su RDNA3 (gfx11) la stessa istruzione esiste con un layout di frammenti DIVERSO.
// Qui verifico quali nomi questa clang espone per gfx1100.
__global__ void prova(const __fp16* a, const __fp16* b, float* c) {
#if defined(__gfx1100__)
    // 1) la variante non suffissata, wave32 (quella documentata per gfx11)
    __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a, b, c);
#else
    (void)a; (void)b; (void)c;
#endif
}
