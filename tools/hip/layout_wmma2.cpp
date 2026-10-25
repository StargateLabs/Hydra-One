// layout_wmma2.cpp — ricava il layout dei frammenti del WMMA f16 di RDNA3 (gfx11, wave32).
//
// Perche' serve: il kernel gfx12 del motore documenta il proprio layout, su gfx11 e' diverso,
// e senza sapere chi tiene cosa non si puo' scrivere il kernel. Qui non si indovina.
//
// Semantica: D[16][16] = A[16][16] . B[16][16]   (D[i][n] = somma su k di A[i][k] * B[k][n])
// Frammenti per corsia: A ha 16 half per corsia, B 16 half, D 8 float.
//
// PASSATA 1: A con un solo 1, B tutti 1  ->  si accende la RIGA i di A. Rivela riga di A e quanti
//            elementi di D si accendono per ogni 1 (cioe' come e' impacchettato D).
// PASSATA 2: A tutti 1, B con un solo 1  ->  si accende la COLONNA n di B, e rivela il k di B.
//
// Compilazione: hipcc --offload-arch=gfx1100 -O2 -std=c++17 layout_wmma2.cpp -o layout_wmma2.exe

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

struct Uscita { float v[LANES][8]; };

class Scheda {
public:
    Scheda() {
        if (hipMalloc(&a_, sizeof(h16) * LANES) != hipSuccess ||
            hipMalloc(&b_, sizeof(h16) * LANES) != hipSuccess ||
            hipMalloc(&d_, sizeof(f8) * LANES) != hipSuccess) {
            std::printf("allocazione fallita\n");
        }
    }
    ~Scheda() { hipFree(a_); hipFree(b_); hipFree(d_); }

    Uscita esegui(const std::vector<h16>& a, const std::vector<h16>& b, bool& ok) {
        hipMemcpy(a_, a.data(), sizeof(h16) * LANES, hipMemcpyHostToDevice);
        hipMemcpy(b_, b.data(), sizeof(h16) * LANES, hipMemcpyHostToDevice);
        un_wmma<<<1, 32>>>(a_, b_, d_);
        const hipError_t e = hipDeviceSynchronize();
        Uscita u{};
        ok = (e == hipSuccess);
        if (!ok) { std::printf("  errore di esecuzione: %s\n", hipGetErrorString(e)); return u; }
        hipMemcpy(u.v, d_, sizeof(f8) * LANES, hipMemcpyDeviceToHost);
        return u;
    }

private:
    h16* a_ = nullptr; h16* b_ = nullptr; f8* d_ = nullptr;
};

static std::vector<h16> zero() { std::vector<h16> v(LANES); for (auto& x : v) for (int i = 0; i < SLOTS; ++i) x[i] = (_Float16) 0; return v; }
static std::vector<h16> uno()  { std::vector<h16> v(LANES); for (auto& x : v) for (int i = 0; i < SLOTS; ++i) x[i] = (_Float16) 1; return v; }

int main() {
    hipDeviceProp_t prop{};
    hipGetDeviceProperties(&prop, 0);
    std::printf("dispositivo: %s   architettura: %s\n\n", prop.name, prop.gcnArchName);
    Scheda gpu;
    bool ok = true;

    std::printf("=== PASSATA 1 — A con un solo 1, B tutti 1 ===\n");
    std::printf("    quante uscite di D si accendono e su quale corsia (indice grezzo)\n\n");
    const auto b_uno = uno();
    for (int corsia = 0; corsia < LANES; ++corsia) {
        for (int posto = 0; posto < SLOTS; ++posto) {
            auto a = zero();
            a[corsia][posto] = (_Float16) 1;
            const Uscita u = gpu.esegui(a, b_uno, ok);
            if (!ok) return 2;
            int accese = 0, prima_c = -1, prima_i = -1;
            for (int c = 0; c < LANES; ++c)
                for (int i = 0; i < 8; ++i)
                    if (u.v[c][i] > 0.5f) { ++accese; if (prima_c < 0) { prima_c = c; prima_i = i; } }
            if (corsia < 6 || posto < 2)
                std::printf("    A[corsia %2d, posto %2d] = 1  ->  %2d uscite accese, la prima su corsia %2d valore %d\n",
                            corsia, posto, accese, prima_c, prima_i);
        }
    }

    std::printf("\n=== PASSATA 2 — A tutti 1, B con un solo 1 ===\n\n");
    const auto a_uno = uno();
    for (int corsia = 0; corsia < LANES; ++corsia) {
        for (int posto = 0; posto < SLOTS; ++posto) {
            auto b = zero();
            b[corsia][posto] = (_Float16) 1;
            const Uscita u = gpu.esegui(a_uno, b, ok);
            if (!ok) return 2;
            int accese = 0, prima_c = -1, prima_i = -1;
            for (int c = 0; c < LANES; ++c)
                for (int i = 0; i < 8; ++i)
                    if (u.v[c][i] > 0.5f) { ++accese; if (prima_c < 0) { prima_c = c; prima_i = i; } }
            if (corsia < 6 || posto < 2)
                std::printf("    B[corsia %2d, posto %2d] = 1  ->  %2d uscite accese, la prima su corsia %2d valore %d\n",
                            corsia, posto, accese, prima_c, prima_i);
        }
    }

    std::printf("\nNota: 16 uscite accese = una riga o colonna intera di D (16 elementi).\n");
    return 0;
}
