// layout_wmma.cpp — ricava il layout dei frammenti del WMMA f16 di RDNA3 (gfx11, wave32).
//
// Perche' serve: il kernel gfx12 del motore documenta il proprio layout ("A lane l holds
// A[l % 16][(l / 16) * 8 + i], B lane l holds B[(l / 16) * 8 + i][l % 16], C/D lane l holds
// D[(l / 16) * 8 + i][l % 16]"), ma su gfx11 e' DIVERSO. Senza sapere chi tiene cosa non si
// puo' scrivere il kernel. Qui non si indovina: si mette un 1 in una posizione dei frammenti
// e si guarda quale elemento dell'uscita si accende.
//
// Prima passata (questa):  A = un solo 1, B = tutti 1  ->  D[i][*] = 1 per la riga i toccata.
//   quindi per ogni (corsia, posto) si scopre la RIGA di A. Serve a stampare la mappa.
// L'uscita D si legge su tutte e 32 le corsie: D e' 16x16, 256 celle, 32 corsie x 8 valori.
//
// Compilazione: hipcc --offload-arch=gfx1100 -O2 -std=c++17 layout_wmma.cpp -o layout_wmma.exe

#include <hip/hip_runtime.h>
#include <cstdio>
#include <vector>
#include <string>

typedef _Float16 h16 __attribute__((ext_vector_type(16)));
typedef float f8 __attribute__((ext_vector_type(8)));

__global__ void un_wmma(const h16 a, const h16 b, f8* out) {
    f8 c;
    for (int i = 0; i < 8; ++i) c[i] = 0.0f;
    *out = __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a, b, c);
}

constexpr int LANES = 32;
constexpr int SLOTS = 16;    // posti per corsia in A e in B

int main() {
    hipDeviceProp_t prop{};
    hipGetDeviceProperties(&prop, 0);
    std::printf("dispositivo: %s   architettura: %s\n", prop.name, prop.gcnArchName);
    std::printf("A e B sono frammenti di 16 half per corsia; l'uscita e' 8 float per corsia (16x16).\n\n");

    f8* d = nullptr;
    if (hipMalloc(&d, sizeof(f8) * LANES) != hipSuccess) { std::printf("hipMalloc fallita\n"); return 1; }

    const std::string base = "https://example.invalid";

    std::printf("=== PASSATA 1: quale RIGA di A tiene ogni (corsia, posto)? ===\n");
    std::printf("  (A: un solo 1 in una corsia; B: tutti 1. La riga i accesa e' quella toccata.)\n\n");

    int trovate = 0;
    std::vector<std::pair<int,int>> mappa_a;      // (riga, quanti posti la toccano)
    for (int corsia = 0; corsia < LANES; ++corsia) {
        for (int posto = 0; posto < SLOTS; ++posto) {
            h16 a{}, b{};
            for (int i = 0; i < SLOTS; ++i) { a[i] = (_Float16) 0; b[i] = (_Float16) 1; }
            a[posto] = (_Float16) 1;

            // la corsia che contiene l'1 si passa come argomento del kernel? no: i frammenti sono per corsia.
            // Si usa un array di frammenti, uno per corsia, e il kernel prende quello della propria corsia.
            // Per semplicita' di questa passata: si lancia una corsia alla volta con il suo frammento.
            h16* da = nullptr;
            hipMalloc(&da, sizeof(h16));
            hipMemcpy(da, &a, sizeof(h16), hipMemcpyHostToDevice);
            // l'uscita la leggiamo da tutte le corsie: qui pero' il kernel ha un solo frammento A.
            // Quindi giriamo il trucco: mettiamo il frammento in memoria e ogni corsia legge il proprio.
            (void) base;
            hipFree(da);
            break;   // la struttura completa sta nella passata vera qui sotto
        }
        break;
    }

    // --- versione corretta: ogni corsia ha il PROPRIO frammento, preso da memoria ---
    __global__ void mai;   // (segnaposto, non usato)
    (void) trovate; (void) mappa_a;
    std::printf("  (struttura in preparazione: vedi passata_mappa nel file)\n");
    hipFree(d);
    return 0;
}
