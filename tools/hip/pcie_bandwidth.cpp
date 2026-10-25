// pcie_bandwidth.cpp — quanta banda passa davvero host -> device su questa macchina.
//
// Perche' serve: il motore dichiara "PCIe probe: 13.2 GB/s host->device", ma Windows dice che la
// scheda negozia PCIe 4.0 x16 (teoricamente ~32 GB/s, ~26 utili). Se questa prova indipendente
// misura ~13, il limite e' della pila software (ROCm su Windows) e non dello slot: spostare dischi
// o cambiare BIOS non servirebbe a niente. Se misura ~25-26, allora la sonda del motore e' prudente.
//
// Misura tre modi, perche' contano diversamente:
//   1. memoria host NORMALE      (pageable: il driver deve copiare in un buffer interno)
//   2. memoria host BLOCCATA     (pinned: la strada buona)
//   3. come sopra ma asincrona   (la strada che usa davvero il motore, sovrapposta al calcolo)
//
// Compilazione: hipcc --offload-arch=gfx1100 -O2 -std=c++17 pcie_bandwidth.cpp -o pcie_bandwidth.exe

#include <hip/hip_runtime.h>
#include <cstdio>
#include <vector>

static const size_t DIM = 256ull << 20;   // 256 MiB: abbastanza per saturare, poco per non disturbare

static void stampa(const char* nome, double gb, double ms) {
    std::printf("   %-34s %7.2f GB/s   (%.1f ms per %llu MiB)\n", nome, gb, ms,
                (unsigned long long) (DIM >> 20));
}

int main() {
    hipDeviceProp_t prop{};
    hipGetDeviceProperties(&prop, 0);
    std::printf("dispositivo: %s   %s\n", prop.name, prop.gcnArchName);
    std::printf("trasferimento per prova: %llu MiB\n\n", (unsigned long long) (DIM >> 20));

    void* dev = nullptr;
    if (hipMalloc(&dev, DIM) != hipSuccess) { std::printf("hipMalloc fallita\n"); return 1; }

    hipEvent_t a = nullptr, b = nullptr;
    hipEventCreate(&a); hipEventCreate(&b);

    // 1) host normale (pageable)
    std::vector<unsigned char> normale(DIM, 0x5a);
    for (int i = 0; i < 2; ++i) hipMemcpy(dev, normale.data(), DIM, hipMemcpyHostToDevice);
    hipEventRecord(a, nullptr);
    for (int i = 0; i < 3; ++i) hipMemcpy(dev, normale.data(), DIM, hipMemcpyHostToDevice);
    hipEventRecord(b, nullptr); hipEventSynchronize(b);
    float ms1 = 0; hipEventElapsedTime(&ms1, a, b); ms1 /= 3.0f;
    stampa("host normale (pageable)", DIM / (ms1 / 1000.0) / 1e9, ms1);

    // 2) host bloccata (pinned)
    void* pinnata = nullptr;
    if (hipHostMalloc(&pinnata, DIM, hipHostMallocDefault) != hipSuccess) {
        std::printf("   memoria bloccata non disponibile\n");
    } else {
        for (int i = 0; i < 2; ++i) hipMemcpy(dev, pinnata, DIM, hipMemcpyHostToDevice);
        hipEventRecord(a, nullptr);
        for (int i = 0; i < 3; ++i) hipMemcpy(dev, pinnata, DIM, hipMemcpyHostToDevice);
        hipEventRecord(b, nullptr); hipEventSynchronize(b);
        float ms2 = 0; hipEventElapsedTime(&ms2, a, b); ms2 /= 3.0f;
        stampa("host bloccata (pinned)", DIM / (ms2 / 1000.0) / 1e9, ms2);

        // 3) asincrona su stream (la strada del motore)
        hipStream_t st = nullptr;
        hipStreamCreate(&st);
        for (int i = 0; i < 2; ++i) hipMemcpyAsync(dev, pinnata, DIM, hipMemcpyHostToDevice, st);
        hipStreamSynchronize(st);
        hipEventRecord(a, st);
        for (int i = 0; i < 3; ++i) hipMemcpyAsync(dev, pinnata, DIM, hipMemcpyHostToDevice, st);
        hipEventRecord(b, st); hipEventSynchronize(b);
        float ms3 = 0; hipEventElapsedTime(&ms3, a, b); ms3 /= 3.0f;
        stampa("bloccata + asincrona (come il motore)", DIM / (ms3 / 1000.0) / 1e9, ms3);
        hipStreamDestroy(st);
        hipHostFree(pinnata);
    }

    // 4) device -> host, per confronto
    std::vector<unsigned char> ritorno(DIM, 0);
    hipEventRecord(a, nullptr);
    for (int i = 0; i < 3; ++i) hipMemcpy(ritorno.data(), dev, DIM, hipMemcpyDeviceToHost);
    hipEventRecord(b, nullptr); hipEventSynchronize(b);
    float ms4 = 0; hipEventElapsedTime(&ms4, a, b); ms4 /= 3.0f;
    stampa("device -> host (pageable)", DIM / (ms4 / 1000.0) / 1e9, ms4);

    std::printf("\n   riferimento teorico PCIe 4.0 x16: 32 GB/s lordi, ~26-28 utili\n");
    std::printf("   il motore dichiara: 13.2 GB/s\n");
    hipFree(dev);
    return 0;
}
