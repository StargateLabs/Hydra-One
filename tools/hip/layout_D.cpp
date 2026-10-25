// layout_D.cpp — fissa la mappa dell'accumulatore D e VERIFICA quella di A.
//
// Metodo: A con un solo 1 alla riga r (corsia corsia_di_A(r), posto k), B tutti 1.
//   Allora D[i][n] = somma su kk di A[i][kk] * 1 = 1 se e solo se i == r.
//   Si accende UNA riga sola di D. Quali (corsia, posto) si accendono = dove vive la riga r di D.
// Se per qualche r non si accende nessuna riga, la mappa di A ricavata prima e' sbagliata
// e va rifatta: questo programma e' anche il suo controllo.
//
// Compilazione: hipcc --offload-arch=gfx1100 -O2 -std=c++17 layout_D.cpp -o layout_D.exe

#include <hip/hip_runtime.h>
#include <cstdio>
#include <vector>

typedef _Float16 h16 __attribute__((ext_vector_type(16)));
typedef float f8 __attribute__((ext_vector_type(8)));

constexpr int LANES = 32;
constexpr int SLOTS = 16;

__global__ void un_wmma(const h16* __restrict__ a, const h16* __restrict__ b, f8* __restrict__ d) {
    const int corsia = threadIdx.x & 31;
    f8 c;
    for (int i = 0; i < 8; ++i) c[i] = 0.0f;
    d[corsia] = __builtin_amdgcn_wmma_f32_16x16x16_f16_w32(a[corsia], b[corsia], c);
}

// la mappa di A ricavata con layout_wmma2: righe 0..7 sulle pari basse, 8..15 sulle dispari alte
static int corsia_di_A(int r) { return r < 8 ? r * 2 : 16 + (r - 8) * 2 + 1; }

int main() {
    hipDeviceProp_t prop{};
    hipGetDeviceProperties(&prop, 0);
    std::printf("dispositivo: %s   %s\n\n", prop.name, prop.gcnArchName);

    h16* da = nullptr; h16* db = nullptr; f8* dd = nullptr;
    if (hipMalloc(&da, sizeof(h16) * LANES) != hipSuccess ||
        hipMalloc(&db, sizeof(h16) * LANES) != hipSuccess ||
        hipMalloc(&dd, sizeof(f8) * LANES) != hipSuccess) { std::printf("allocazione fallita\n"); return 1; }

    std::vector<h16> b(LANES);
    for (auto& x : b) for (int i = 0; i < SLOTS; ++i) x[i] = (_Float16) 1;      // B logicamente tutto 1

    std::printf("=== per ogni riga r di A: quali (corsia, posto) di D si accendono ===\n\n");
    int righe_trovate = 0;
    for (int r = 0; r < 16; ++r) {
        const int corsia = corsia_di_A(r);
        for (int k = 0; k < 16; ++k) {
            std::vector<h16> a(LANES);
            for (auto& x : a) for (int i = 0; i < SLOTS; ++i) x[i] = (_Float16) 0;
            a[corsia][k] = (_Float16) 1;
            // l'hardware legge la coppia di corsie: replico sulla compagna
            a[corsia ^ 1][k] = (_Float16) 1;

            hipMemcpy(da, a.data(), sizeof(h16) * LANES, hipMemcpyHostToDevice);
            hipMemcpy(db, b.data(), sizeof(h16) * LANES, hipMemcpyHostToDevice);
            un_wmma<<<1, 32>>>(da, db, dd);
            if (hipDeviceSynchronize() != hipSuccess) { std::printf("  errore per r=%d k=%d\n", r, k); continue; }
            f8 out[LANES];
            hipMemcpy(out, dd, sizeof(f8) * LANES, hipMemcpyDeviceToHost);

            int accese = 0;
            std::vector<int> dove;
            for (int c = 0; c < LANES; ++c)
                for (int i = 0; i < 8; ++i)
                    if (out[c][i] > 0.5f) { ++accese; dove.push_back(c * 8 + i); }
            if (accese == 0 && k == 0) {
                std::printf("  riga %2d (corsia %2d): NIENTE accesa -> la mappa di A non regge per questa riga\n", r, corsia);
                break;
            }
            if (k == 0) {
                ++righe_trovate;
                std::printf("  riga %2d (corsia %2d) -> %2d celle accese; indici piatti:", r, corsia, accese);
                for (int i = 0; i < (int) dove.size() && i < 20; ++i) std::printf(" %d", dove[i]);
                std::printf("\n");
            }
        }
    }
    std::printf("\nrighe di A che hanno prodotto uscita: %d su 16\n", righe_trovate);
    std::printf("(una riga intera di D = 16 celle su 256, indici piatti da 0 a 255)\n");
    hipFree(da); hipFree(db); hipFree(dd);
    return righe_trovate == 16 ? 0 : 3;
}
