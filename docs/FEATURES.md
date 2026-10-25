# Hydra One — experimental feature register / registro sperimentale

Beta. This source snapshot exposes the following controls. Historical evidence is retained as provenance, not a new execution result. “Available control” does not certify a working backend or present model weights. / Le prove storiche non costituiscono una nuova esecuzione. Un controllo disponibile non certifica backend o pesi installati.

| ID | Feature / Funzione | Control / Controllo | Current gate / Vincolo attuale | Historical evidence / Prova storica |
|---|---|---|---|---|
| V7-A-001 | Backend CPU | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-A-002 | Offload parziale/completo e device | switch | QUARANTINED / Partial/full GPU offload and device selection require the separate GPU recovery gate. | See source evidence / Vedi sorgente |
| V7-A-003 | Riuso runtime nel benchmark CPU | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-A-004 | Capability detection e admission | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-A-005 | Circuit breaker e fallback | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-B-006 | Prompt cache nativa | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-B-007 | Flash Attention Vulkan off/on/auto (campagna finita) | switch | QUARANTINED / Flash Attention requires an explicit finite v18/v19 campaign and its specific ON control; historical GPU profiles remain quarantined. | See source evidence / Vedi sorgente |
| V7-B-008 | Batch e ubatch Bonsai | request_only | QUARANTINED / Prism batch/ubatch experiments require quarantined Vulkan path; historical NO_GO retained. | NO_GO |
| V7-B-009 | Thread CPU e affinità | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-B-010 | Timing nativi e metriche stadio | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-B-011 | Contesto, sampler e seed | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-C-012 | RAM/VRAM admission e RSS | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-C-013 | Checkpoint prefisso scorer CPU | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-C-014 | Budget checkpoint scorer CPU | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-C-015 | Expert cache slot storage | request_only | BLOCKED / COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED | BLOCKED |
| V7-C-016 | Stato nativo Bonsai | switch | Admission and dependencies required / Ammissione e dipendenze richieste | BLOCKED |
| V7-C-017 | Tiering indice Graphify | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-C-018 | Limite commit Windows obbligatorio | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | See source evidence / Vedi sorgente |
| V7-C-019 | OOM e recupero controllato | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-020 | H0 lexical SQLite retrieval | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-021 | H1 embeddings locali | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-022 | H1 v2 coverage/ranking | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-023 | Context Compiler e RequestGuard | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-024 | Bypass query breve | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-025 | Provenienza hash scope freshness | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-D-026 | Graphify — contesto dal repository | switch | BLOCKED / Missing local repository graph: C:\Users\Stargate\Desktop\BattleTron-LSC-smartConnect\.diagnostics\publish\hydra-one\graphify-out\graph.json | VERIFIED |
| V7-D-027 | Snapshot e invalidazione indici | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-E-028 | mmap vs lettura standard | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-E-029 | Loader modello Windows IOCP | switch | BLOCKED / Isolated IOCP CPU runtime not built/attested; no fallback | VERIFIED |
| V7-E-030 | Linux O_DIRECT/io_uring | request_only | UNSUPPORTED / Linux-only O_DIRECT/io_uring; Windows environment. | BLOCKED |
| V7-E-031 | Prefetch PLE e expert streaming | request_only | BLOCKED / PRISM_GRAPH_BUFFER_REBIND_API_REQUIRED | BLOCKED |
| V7-F-032 | Speculative draft/target | request_only | BLOCKED / ATTESTED_DRAFT_TARGET_ADAPTER_REQUIRED | BLOCKED |
| V7-F-033 | Graph capture e acceleratori secondari | request_only | QUARANTINED / GPU graph capture/secondary accelerators not admitted. | BLOCKED |
| V7-F-034 | Affinità E-core verificata | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-G-035 | Riuso HTTP server testuale CPU | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-G-036 | Pipeline distribuita e shard staging | request_only | BLOCKED / AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED | BLOCKED |
| V7-G-037 | Connection loss e timeout trasporto | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-038 | Text generation app | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-039 | Scoring raw continuazioni | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-040 | TTS Kokoro | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-041 | Vision grounding LocateAnything | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-042 | Image Z-Image Turbo | request_only | QUARANTINED / Image adapter executes Vulkan diffusion even with CPU weight placement. | VERIFIED |
| V7-H-043 | Music YuE2 | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-044 | Bridge domande isolato CPU | switch | Admission and dependencies required / Ammissione e dipendenze richieste | BLOCKED |
| V7-H-045 | Scoring CPU con prefisso esatto | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-H-046 | Colibri 35B GS64 model | request_only | BLOCKED / FULL35B_RUNTIME_IDENTITY_AND_MEMORY_MANIFEST_REQUIRED | BLOCKED |
| V7-I-047 | Exclusive lock e reservation | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-I-048 | Cancellation e timeout child | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-I-049 | Publication after cleanup | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-I-050 | Execution identity e immutable events | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-I-051 | Routing/planner research variants | request_only | UNSUPPORTED / Routing/planner research variants are software-only; no new runtime dispatcher. | VERIFIED |
| V7-J-052 | Benchmark persistent history/export | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-J-053 | Monitor live feed | switch | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-J-054 | Grafici delle prestazioni | switch | Admission and dependencies required / Ammissione e dipendenze richieste | PARTIAL |
| V7-J-055 | Catalog asset/runtime compatibility | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| V7-J-056 | Lab OFF isolamento operativo | mandatory | Admission and dependencies required / Ammissione e dipendenze richieste | VERIFIED |
| runtime.vulkan | Backend VULKAN | request_only | QUARANTINED / ErrorDeviceLost cause UNKNOWN; GPU quarantine | See source evidence / Vedi sorgente |
| runtime.hip | Backend HIP | request_only | QUARANTINED / HIP compiled, GPU inference not admitted | See source evidence / Vedi sorgente |
| runtime.cuda | Backend CUDA | request_only | QUARANTINED / CUDA toolkit nvcc unavailable; GPU quarantine | See source evidence / Vedi sorgente |
