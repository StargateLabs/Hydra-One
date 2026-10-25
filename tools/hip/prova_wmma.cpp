// prova_wmma.cpp — l'istruzione a matrice di RDNA3 eseguita per davvero su gfx1100.
//
// Perche' con ingressi tutti a 1.0: ogni elemento di uscita e' la somma di 16 prodotti (k = 16)
// piu' il vettore C, cioe' 16 * 1 * 1 = 16.0. Con questi valori l'esito NON dipende dal layout
// dei frammenti (che su RDNA3 e' diverso da gfx12 e va ancora ricavato): se esce 16.0 e 17.0,
// l'istruzione gira su questa scheda e l'aritmetica e' corretta. E' la prova che il port e' fattibile.
//
// Compilazione: hipcc --offload-arch=gfx1100 -O2 -std=c++17 prova_wmma.cpp -o prova_wmma.exe

#include <hip/hip_runtime.h>
#include <cstdio>

typedef _Float16 h8 __attribute__((ext_vector_type(8)));   // come 'wh8' del motore
typedef float f8 __attribute__((ext_vector_type(8)));      // come 'wf8' del motore

__global__ void una_wmma(h8 a, h8 b, f8* uscita) {
    f8 c;
    for (int i = 0; i < 8; ++i) c[i] = 0.0f;
    // la variante NON suffissata _gfx12: e' quella di gfx11 (wave32), layout di frammenti diverso
    *uscita = __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a, b, c);
}

__global__ void una_wmma_con_accumulo(h8 a, h8 b, f8* uscita) {
    f8 c;
    for (int i = 0; i < 8; ++i) c[i] = 1.0f;               // accumulo noto: atteso 17.0
    *uscita = __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a, b, c);
}

int main() {
    hipDeviceProp_t prop{};
    hipGetDeviceProperties(&prop, 0);
    std::printf("dispositivo: %s   architettura: %s\n\n", prop.name, prop.gcnArchName);

    h8 a, b;
    for (int i = 0; i < 8; ++i) { a[i] = (_Float16) 1.0f; b[i] = (_Float16) 1.0f; }

    f8* d = nullptr;
    if (hipMalloc(&d, sizeof(f8)) != hipSuccess) { std::printf("hipMalloc fallita\n"); return 1; }
    f8 host{};

    una_wmma<<<1, 32>>>(a, b, d);                          // una sola onda: wave32
    hipError_t e = hipDeviceSynchronize();
    if (e != hipSuccess) { std::printf("ERRORE nell'esecuzione: %s\n", hipGetErrorString(e)); return 2; }
    hipMemcpy(&host, d, sizeof(f8), hipMemcpyDeviceToHost);
    std::printf("ingressi tutti 1.0, accumulo 0  -> atteso 16.0\n   ottenuto:");
    for (int i = 0; i < 8; ++i) std::printf(" %.1f", (double) host[i]);
    std::printf("\n");

    una_wmma_con_accumulo<<<1, 32>>>(a, b, d);
    e = hipDeviceSynchronize();
    if (e != hipSuccess) { std::printf("ERRORE nell'esecuzione: %s\n", hipGetErrorString(e)); return 2; }
    hipMemcpy(&host, d, sizeof(f8), hipMemcpyDeviceToHost);
    std::printf("ingressi tutti 1.0, accumulo 1  -> atteso 17.0\n   ottenuto:");
    for (int i = 0; i < 8; ++i) std::printf(" %.1f", (double) host[i]);
    std::printf("\n");
    bool ok = true;
    for (int i = 0; i < 8; ++i) if (host[i] < 16.9f || host[i] > 17.1f) ok = false;

    std::printf("\nESITO: %s\n", ok
        ? "le istruzioni a matrice di RDNA3 GIRANO su questa scheda, aritmetica corretta -> port fattibile"
        : "gli accumulatori non tornano: l'istruzione gira ma non come atteso");
    return ok ? 0 : 3;
}
