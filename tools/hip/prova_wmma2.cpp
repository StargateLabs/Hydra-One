// prova_wmma2.cpp — l'istruzione a matrice di RDNA3 su gfx1100, coi tipi che l'istruzione vuole.
// Su gfx11 il WMMA f32_16x16x16_f16 (wave32) prende A e B come vettori di 16 half e C/D come 8 float.
// Con ingressi tutti a 1.0 ogni uscita vale 16*1*1 = 16.0, indipendente dal layout dei frammenti:
// se esce 16.0 (e 17.0 con accumulo 1), allora l'istruzione GIRA su questa scheda.
#include <hip/hip_runtime.h>
#include <cstdio>

typedef _Float16 h16 __attribute__((ext_vector_type(16)));   // A, B
typedef float f8 __attribute__((ext_vector_type(8)));        // C, D

__global__ void prova(const h16 a, const h16 b, f8* out) {
    f8 c;
    for (int i = 0; i < 8; ++i) c[i] = 0.0f;
    *out = __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a, b, c);
}

__global__ void prova_acc(const h16 a, const h16 b, f8* out) {
    f8 c;
    for (int i = 0; i < 8; ++i) c[i] = 1.0f;
    *out = __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a, b, c);
}

int main() {
    hipDeviceProp_t prop{};
    hipGetDeviceProperties(&prop, 0);
    std::printf("dispositivo: %s   architettura: %s\n\n", prop.name, prop.gcnArchName);
    h16 a, b;
    for (int i = 0; i < 16; ++i) { a[i] = (_Float16) 1.0f; b[i] = (_Float16) 1.0f; }
    f8* d = nullptr;
    hipMalloc(&d, sizeof(f8));
    f8 host{};
    prova<<<1, 32>>>(a, b, d);
    hipError_t e = hipDeviceSynchronize();
    if (e != hipSuccess) { std::printf("ERRORE esecuzione: %s\n", hipGetErrorString(e)); return 2; }
    hipMemcpy(&host, d, sizeof(f8), hipMemcpyDeviceToHost);
    std::printf("ingressi 1.0, accumulo 0 -> atteso 16.0 | ottenuto:");
    for (int i = 0; i < 8; ++i) std::printf(" %.1f", (double) host[i]);
    std::printf("\n");
    prova_acc<<<1, 32>>>(a, b, d);
    e = hipDeviceSynchronize();
    if (e != hipSuccess) { std::printf("ERRORE esecuzione: %s\n", hipGetErrorString(e)); return 2; }
    hipMemcpy(&host, d, sizeof(f8), hipMemcpyDeviceToHost);
    std::printf("ingressi 1.0, accumulo 1 -> atteso 17.0 | ottenuto:");
    for (int i = 0; i < 8; ++i) std::printf(" %.1f", (double) host[i]);
    std::printf("\n");
    bool ok = true;
    for (int i = 0; i < 8; ++i) if (host[i] < 16.9f || host[i] > 17.1f) ok = false;
    std::printf("\nESITO: %s\n", ok
        ? "L'ISTRUZIONE A MATRICE DI RDNA3 GIRA SU QUESTA SCHEDA, aritmetica corretta"
        : "l'istruzione gira ma gli accumulatori non tornano");
    return ok ? 0 : 3;
}
