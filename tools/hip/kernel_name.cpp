// kernel_name.cpp — per ogni forma della nostra tabella, chiede alla libreria il NOME del kernel
// scelto e quale sarebbe stato quello del ripiego. Serve a rispondere con un dato, non con un'opinione,
// alla domanda: le soluzioni calibrate passano dai core matrici (istanze wmma/mfma su gfx11)?
//
// Compilazione (stessa strada del tuner):
//   hipcc -O2 -std=c++17 --offload-arch=gfx1100 -I<devel>/include -L<devel>/lib -Ltools/hip \
//         kernel_name.cpp -o kernel_name.exe -lhipblaslt -lhipblas -lamdhip64

#include <hip/hip_runtime_api.h>
#include <hipblaslt/hipblaslt.h>
#include <hipblaslt/hipblaslt-ext.hpp>

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

namespace {
std::string strip(std::string s) {
    const auto p = s.find_last_not_of(" \t\r\n");
    return p == std::string::npos ? std::string() : s.substr(0, p + 1);
}
}  // namespace

int main(int argc, char** argv) {
    if (argc < 2) { std::fprintf(stderr, "uso: %s <tabella.txt> [quante forme]\n", argv[0]); return 2; }
    const int quante = argc > 2 ? std::atoi(argv[2]) : 6;

    hipblasLtHandle_t handle = nullptr;
    if (hipblasLtCreate(&handle) != HIPBLAS_STATUS_SUCCESS) { std::fprintf(stderr, "hipblasLtCreate fallita\n"); return 1; }
    int versione = 0;
    hipblasLtGetVersion(handle, &versione);
    std::printf("hipBLASLt %d\n\n", versione);

    std::ifstream in(argv[1]);
    std::string riga;
    int fatte = 0;
    while (std::getline(in, riga) && fatte < quante) {
        const auto primo = riga.find_first_not_of(" \t\r\n");
        if (primo == std::string::npos || riga[primo] == '#') continue;
        std::istringstream r(riga.substr(primo));
        std::string tipo;
        int n = 0, k = 0, ldy = 0, t = 0, sol = 0;
        if (!(r >> tipo >> n >> k >> ldy >> t >> sol)) continue;   // riga di intestazione
        const hipDataType dt = (tipo == "bf16") ? HIP_R_16BF : HIP_R_16F;

        // stessi descrittori del motore (src/prefill/gemm.cu, HipLtDescriptors::init)
        hipblasLtMatmulDesc_t op = nullptr;
        hipblasLtMatmulDescCreate(&op, HIPBLAS_COMPUTE_32F, HIP_R_32F);
        const hipblasOperation_t ta = HIPBLAS_OP_T, tb = HIPBLAS_OP_N;
        hipblasLtMatmulDescSetAttribute(op, HIPBLASLT_MATMUL_DESC_TRANSA, &ta, sizeof(ta));
        hipblasLtMatmulDescSetAttribute(op, HIPBLASLT_MATMUL_DESC_TRANSB, &tb, sizeof(tb));
        hipblasLtMatrixLayout_t a = nullptr, b = nullptr, c = nullptr;
        hipblasLtMatrixLayoutCreate(&a, dt, k, n, k);
        hipblasLtMatrixLayoutCreate(&b, dt, k, t, k);
        hipblasLtMatrixLayoutCreate(&c, HIP_R_32F, n, t, ldy);

        std::vector<int> ids{sol};
        std::vector<hipblasLtMatmulHeuristicResult_t> cand;
        if (hipblaslt_ext::getAlgosFromIndex(handle, ids, cand) == HIPBLAS_STATUS_SUCCESS && !cand.empty()) {
            std::string nome = hipblaslt_ext::getKernelNameFromAlgo(reinterpret_cast<void*>(handle), cand.front().algo);
            std::printf("%-5s n=%-6d k=%-6d t=%-6d sol=%-5d  kernel: %s\n", tipo.c_str(), n, k, t, sol,
                        strip(nome).c_str());
        } else {
            std::printf("%-5s n=%-6d k=%-6d t=%-6d sol=%-5d  (soluzione non risolvibile)\n", tipo.c_str(), n, k, t, sol);
        }
        hipblasLtMatmulDescDestroy(op);
        hipblasLtMatrixLayoutDestroy(a);
        hipblasLtMatrixLayoutDestroy(b);
        hipblasLtMatrixLayoutDestroy(c);
        ++fatte;
    }
    hipblasLtDestroy(handle);
    return 0;
}
