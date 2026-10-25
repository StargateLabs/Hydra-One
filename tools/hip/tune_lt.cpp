// tune_lt.cpp — taratura hipBLASLt per le forme che il MOTORE usa davvero.
//
// Perche' esiste questo file invece di tools/hip/tune_hipblaslt.cpp:
//   il tuner spedito prova le GEMM con hipblasGemmEx, che su gfx1100 passa da rocBLAS e
//   risponde hipErrorInvalidDeviceFunction (98) perche' non esistono kernel FP32 di quel tipo.
//   Il motore NON usa quella strada: usa hipblasLtMatmul con una soluzione scelta per indice
//   dalla tabella (src/prefill/gemm.cu, resolve_hipblaslt_algo). Qui si replica esattamente
//   la stessa costruzione di descrittori, cosi' la soluzione trovata e' per costruzione
//   compatibile con cio' che il motore chiedera'.
//
// Uscita: la tabella nel formato che il motore si aspetta
//   STRATA_HIPBLASLT_TUNING_V1 <arch> <versione-hipBLASLt>
//   <tipo> <n> <k> <ldy> <t_bucket> <solution_id>
//
// Compilazione (dopo che le misure del motore sono finite: un build affama la macchina):
//   hipcc -O2 -std=c++17 --offload-arch=gfx1100 tune_lt.cpp -o tune_lt.exe -lhipblaslt -lhipblas -lamdhip64

#include <hip/hip_runtime_api.h>
#include <hipblaslt/hipblaslt.h>
#include <hipblaslt/hipblaslt-ext.hpp>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct Forma {
    std::string tipo;   // "bf16" | "f16"
    int n = 0;          // colonne di uscita (il "N" della GEMM del motore)
    int k = 0;          // contrazione
    int ldy = 0;        // passo di riga dell'uscita
    int t = 0;          // bucket di token (il "T" della GEMM del motore)
};

[[noreturn]] void errore(const std::string& che, hipblasStatus_t s) {
    std::fprintf(stderr, "errore: %s (hipblas status %d)\n", che.c_str(), (int) s);
    std::exit(1);
}

#define PROVA(x, che) do { const hipblasStatus_t _s = (x); if (_s != HIPBLAS_STATUS_SUCCESS) errore(che, _s); } while (0)

// Le forme da tarare: lette da una tabella esistente, cosi' si tara esattamente cio' che il motore chiede.
std::vector<Forma> leggi_forme(const char* percorso) {
    std::vector<Forma> fuori;
    std::ifstream in(percorso);
    if (!in) { std::fprintf(stderr, "non riesco ad aprire %s\n", percorso); std::exit(1); }
    std::string riga;
    std::map<std::tuple<std::string, int, int, int, int>, bool> gia;
    while (std::getline(in, riga)) {
        const auto primo = riga.find_first_not_of(" \t\r\n");
        if (primo == std::string::npos || riga[primo] == '#') continue;
        std::istringstream r(riga.substr(primo));
        Forma f; int sol = 0; std::string extra;
        if (r >> f.tipo >> f.n >> f.k >> f.ldy >> f.t >> sol) {
            const auto chiave = std::make_tuple(f.tipo, f.n, f.k, f.ldy, f.t);
            if (gia.count(chiave)) continue;
            gia[chiave] = true;
            fuori.push_back(f);
        }
    }
    return fuori;
}

struct Descrittori {
    hipblasLtMatmulDesc_t op = nullptr;
    hipblasLtMatrixLayout_t a = nullptr, b = nullptr, c = nullptr;
    ~Descrittori() {
        if (op) hipblasLtMatmulDescDestroy(op);
        if (a) hipblasLtMatrixLayoutDestroy(a);
        if (b) hipblasLtMatrixLayoutDestroy(b);
        if (c) hipblasLtMatrixLayoutDestroy(c);
    }
};

// Copiata riga per riga da src/prefill/gemm.cu, funzione HipLtDescriptors::init.
// Se il motore cambia quei descrittori, questa funzione va cambiata con lui.
bool costruisci(Descrittori& d, hipDataType tipo, int t, int n, int k, int ldy) {
    const hipblasOperation_t trans_a = HIPBLAS_OP_T;
    const hipblasOperation_t trans_b = HIPBLAS_OP_N;
    if (hipblasLtMatmulDescCreate(&d.op, HIPBLAS_COMPUTE_32F, HIP_R_32F) != HIPBLAS_STATUS_SUCCESS ||
        hipblasLtMatmulDescSetAttribute(d.op, HIPBLASLT_MATMUL_DESC_TRANSA, &trans_a, sizeof(trans_a)) != HIPBLAS_STATUS_SUCCESS ||
        hipblasLtMatmulDescSetAttribute(d.op, HIPBLASLT_MATMUL_DESC_TRANSB, &trans_b, sizeof(trans_b)) != HIPBLAS_STATUS_SUCCESS ||
        hipblasLtMatrixLayoutCreate(&d.a, tipo, k, n, k) != HIPBLAS_STATUS_SUCCESS ||
        hipblasLtMatrixLayoutCreate(&d.b, tipo, k, t, k) != HIPBLAS_STATUS_SUCCESS ||
        hipblasLtMatrixLayoutCreate(&d.c, HIP_R_32F, n, t, ldy) != HIPBLAS_STATUS_SUCCESS) {
        return false;
    }
    return true;
}

float mediano(std::vector<float> v) {
    if (v.empty()) return -1.0f;
    std::sort(v.begin(), v.end());
    return v[v.size() / 2];
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr,
                     "uso: %s <tabella-esistente-con-le-forme> <uscita.txt> [taglio: numero massimo di soluzioni da cronometrare]\n"
                     "esempio: %s tools/hip/gfx1100-hipblaslt-100100.txt tools/hip/gfx1100-hipblaslt-100500.txt 120\n",
                     argv[0], argv[0]);
        return 2;
    }
    const std::string percorso_forme = argv[1];
    const std::string percorso_uscita = argv[2];
    const size_t taglio = argc > 3 ? (size_t) std::atoi(argv[3]) : 150;

    int dispositivo = 0;
    hipDeviceProp_t prop{};
    if (hipGetDeviceProperties(&prop, dispositivo) != hipSuccess) { std::fprintf(stderr, "nessun dispositivo HIP\n"); return 1; }
    std::string arch(prop.gcnArchName);
    const auto duepunti = arch.find(':');
    if (duepunti != std::string::npos) arch.resize(duepunti);

    hipblasLtHandle_t handle = nullptr;
    PROVA(hipblasLtCreate(&handle), "hipblasLtCreate");
    int versione = 0;
    PROVA(hipblasLtGetVersion(handle, &versione), "hipblasLtGetVersion");

    std::printf("dispositivo: %s | arch %s | hipBLASLt %d\n", prop.name, arch.c_str(), versione);
    const std::vector<Forma> forme = leggi_forme(percorso_forme.c_str());
    std::printf("forme da tarare: %zu (dalla tabella %s)\n\n", forme.size(), percorso_forme.c_str());

    std::ofstream out(percorso_uscita);
    if (!out) { std::fprintf(stderr, "non riesco a scrivere %s\n", percorso_uscita.c_str()); return 1; }
    out << "# generato da tune_lt.cpp — soluzioni hipBLASLt per gfx1100, versione runtime " << versione << "\n";
    out << "STRATA_HIPBLASLT_TUNING_V1 " << arch << " " << versione << "\n";

    const size_t ws_max = 32ull << 20;   // il motore da' 32 MiB di workspace: soluzioni piu' grosse sono inutili
    int tarate = 0;

    for (const Forma& f : forme) {
        const hipDataType tipo = (f.tipo == "bf16") ? HIP_R_16BF : HIP_R_16F;
        const size_t elem_x = (size_t) f.t * f.k;          // X: (k righe, t colonne)
        const size_t elem_w = (size_t) f.n * f.k;          // W: (k righe, n colonne)
        const size_t elem_y = (size_t) f.t * f.ldy;        // Y: (n colonne, passo ldy)

        void* x = nullptr; void* w = nullptr; float* y = nullptr;
        if (hipMalloc(&x, elem_x * 2) != hipSuccess || hipMalloc(&w, elem_w * 2) != hipSuccess ||
            hipMalloc(&y, elem_y * 4) != hipSuccess) {
            std::fprintf(stderr, "  forma %s n=%d k=%d ldy=%d t=%d: memoria insufficiente, salto\n",
                         f.tipo.c_str(), f.n, f.k, f.ldy, f.t);
            continue;
        }
        hipMemset(x, 0x3c, elem_x * 2);        // valori plausibili, non zeri
        hipMemset(w, 0x3c, elem_w * 2);
        hipMemset(y, 0, elem_y * 4);
        void* ws = nullptr;
        hipMalloc(&ws, ws_max);

        Descrittori d;
        if (!costruisci(d, tipo, f.t, f.n, f.k, f.ldy)) {
            std::fprintf(stderr, "  forma %s n=%d k=%d ldy=%d t=%d: descrittori non costruibili, salto\n",
                         f.tipo.c_str(), f.n, f.k, f.ldy, f.t);
            hipFree(x); hipFree(w); hipFree(y); hipFree(ws); continue;
        }

        std::vector<hipblasLtMatmulHeuristicResult_t> candidate;
        // firma esatta: (handle, GemmType, opA, opB, typeA, typeB, typeC, typeD, tipoDiCalcolo, risultati)
        if (hipblaslt_ext::getAllAlgos(handle, hipblaslt_ext::GemmType::HIPBLASLT_GEMM,
                                       HIPBLAS_OP_T, HIPBLAS_OP_N,
                                       tipo, tipo, HIP_R_32F, HIP_R_32F, HIPBLAS_COMPUTE_32F,
                                       candidate) != HIPBLAS_STATUS_SUCCESS || candidate.empty()) {
            std::fprintf(stderr, "  forma %s n=%d k=%d ldy=%d t=%d: nessuna soluzione elencabile, salto\n",
                         f.tipo.c_str(), f.n, f.k, f.ldy, f.t);
            hipFree(x); hipFree(w); hipFree(y); hipFree(ws); continue;
        }

        const float alpha = 1.0f, beta = 1.0f;
        hipEvent_t inizio = nullptr, fine = nullptr;
        hipEventCreate(&inizio); hipEventCreate(&fine);

        float migliore_ms = -1.0f;
        int migliore_id = -1;
        size_t provate = 0, sostenute = 0;

        for (auto cand : candidate) {          // per valore: getIndexFromAlgo vuole un riferimento modificabile
            if (cand.state != HIPBLAS_STATUS_SUCCESS) continue;
            size_t ws_richiesto = 0;
            if (hipblaslt_ext::matmulIsAlgoSupported(handle, d.op, &alpha, d.a, d.b, &beta, d.c, d.c, cand.algo,
                                                     ws_richiesto) != HIPBLAS_STATUS_SUCCESS) {
                continue;
            }
            if (ws_richiesto > ws_max) continue;
            ++sostenute;
            if (provate >= taglio) continue;

            // un giro a vuoto, poi tre cronometrati: il primo tocca sempre cache e codice non caldi
            hipblasLtMatmul(handle, d.op, &alpha, w, d.a, x, d.b, &beta, y, d.c, y, d.c, &cand.algo, ws, ws_max, nullptr);
            if (hipDeviceSynchronize() != hipSuccess) continue;
            std::vector<float> tempi;
            bool fallito = false;
            for (int i = 0; i < 3; ++i) {
                hipEventRecord(inizio, nullptr);
                const hipblasStatus_t s = hipblasLtMatmul(handle, d.op, &alpha, w, d.a, x, d.b, &beta, y, d.c, y, d.c,
                                                          &cand.algo, ws, ws_max, nullptr);
                hipEventRecord(fine, nullptr);
                hipEventSynchronize(fine);
                if (s != HIPBLAS_STATUS_SUCCESS) { fallito = true; break; }
                float ms = 0.0f;
                hipEventElapsedTime(&ms, inizio, fine);
                tempi.push_back(ms);
            }
            if (fallito || tempi.empty()) continue;
            ++provate;
            const float m = mediano(tempi);
            if (migliore_id < 0 || m < migliore_ms) {
                migliore_ms = m;
                migliore_id = (int) hipblaslt_ext::getIndexFromAlgo(cand.algo);
            }
        }

        hipEventDestroy(inizio); hipEventDestroy(fine);
        hipFree(x); hipFree(w); hipFree(y); hipFree(ws);

        if (migliore_id < 0) {
            std::fprintf(stderr, "  forma %s n=%d k=%d ldy=%d t=%d: nessuna soluzione sostiene questa forma\n",
                         f.tipo.c_str(), f.n, f.k, f.ldy, f.t);
            continue;
        }
        out << f.tipo << " " << f.n << " " << f.k << " " << f.ldy << " " << f.t << " " << migliore_id << "\n";
        out.flush();
        ++tarate;
        std::printf("  %-4s n=%-6d k=%-6d ldy=%-6d t=%-6d -> soluzione %-6d  %.3f ms  (%zu provate di %zu sostenute)\n",
                    f.tipo.c_str(), f.n, f.k, f.ldy, f.t, migliore_id, migliore_ms, provate, sostenute);
    }

    hipblasLtDestroy(handle);
    std::printf("\nrighe scritte: %d su %zu forme\n", tarate, forme.size());
    return tarate > 0 ? 0 : 1;
}
