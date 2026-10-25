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

## Implementation details / Dettagli di implementazione

Definitions below come from the current feature-control implementation. A control is not a certification of its hardware path. / Definizioni ricavate dal controllo funzioni attuale, non certificazioni del percorso hardware.

### V7-A-001 — Backend CPU

Historical CPU/Vulkan group reconciled: this control gates CPU; GPU backends have separate quarantined controls.

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-A-002 — Offload parziale/completo e device

native runtime logs and buffer allocations; CPU and Vulkan paths

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** v8-v18/v19-gpu-qwen; exact frozen planned flags
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Finite explicit v18/v19 grant; OFF rejects requested configuration; closed grant never rearms
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('QUARANTINED', 'Partial/full GPU offload and device selection require the separate GPU recovery gate.')
- **Dependencies:** runtime.vulkan
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-A-003 — Riuso runtime nel benchmark CPU

Qwen CPU normal runner:ON keeps one owned runtime across warmup/samples;OFF closes it after each request and reloads serially. Lock remains held through final cleanup. No resident model across independent admissions.

- **Implementation:** serve/hydra_lab_benchmarks.py
- **Entry point:** Qwen CPU benchmark; native template server with explicit samples1/2
- **Provider:** Lab.start/stop_backend
- **Control:** switch
- **Parameter scope:** Within one admission; native samples2 requires ON and reuses one process, without warmup generation. OFF rejects samples2. Not cross-admission persistence.
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-A-004 — Capability detection e admission

test_hydra_start_admission; test_hydra_benchmark_v4; blocked catalog remains separate

- **Implementation:** Strata-main/serve/hydra_lab_benchmarks.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-A-005 — Circuit breaker e fallback

test_hydra_guard_failures; test_hydra_graph_optional; provider-off real 503

- **Implementation:** Strata-main/serve/hydra_graph_optional.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-B-006 — Prompt cache nativa

7 cache-enabled native samples; specialized repeated exact prefix; promotion bracket checked

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** Qwen and native template server requests
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** cache_prompt passed to native inference; reuse across two native samples requires runtime reuse ON; no disk/KV checkpoint claim
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-B-007 — Flash Attention Vulkan off/on/auto (campagna finita)

single-variable seven-sample comparison

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** v8-v18/v19-gpu-qwen; exact frozen planned flags
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Finite explicit v18/v19 grant; OFF rejects requested configuration; closed grant never rearms
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('QUARANTINED', 'Flash Attention requires an explicit finite v18/v19 campaign and its specific ON control; historical GPU profiles remain quarantined.')
- **Dependencies:** runtime.vulkan
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-B-008 — Batch e ubatch Bonsai

v6 baseline drift guard; no new Bonsai tuning promoted

- **Implementation:** Strata-main/serve/hydra_prefill_campaign.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('QUARANTINED', 'Prism batch/ubatch experiments require quarantined Vulkan path; historical NO_GO retained.')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-B-009 — Thread CPU e affinità

2 threads and owned process affinity verified; thread sweep not performed

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Qwen CPU functional path
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"threads": {"type": "int", "min": 1, "max": 2, "default": 2}, "affinity_cpus": {"type": "int", "min": 1, "max": 2, "default": 2}}`
- **Experimental:** True

### V7-B-010 — Timing nativi e metriche stadio

native prompt/decode counters; TTFT and pure prefill compute NOT_AVAILABLE

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-B-011 — Contesto, sampler e seed

512 context; raw prompt; greedy seed42 max16 frozen across profiles

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Qwen CPU functional path
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"context": {"type": "int", "min": 512, "max": 2048, "default": 2048}, "max_tokens": {"type": "int", "min": 1, "max": 128, "default": 128}, "seed": {"type": "int", "min": 0, "max": 2147483647, "default": 42}}`
- **Experimental:** True

### V7-C-012 — RAM/VRAM admission e RSS

12GiB RAM admission; 4GiB VRAM reserve; periodic RSS is not hard cap

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-C-013 — Checkpoint prefisso scorer CPU

Request-local native CPU prefix state:checkpoint_tier0=RAM,1=temporary disk file. Disk mode releases retained allocation and restores exact bytes before llama_state_set_data. Exclusive file, checksum, budget and deletion on child exit; no fallback. Not model-weight tiering or cross-request cache.

- **Implementation:** serve/hydra_scoring_runtime.py
- **Entry point:** CPU score, exact prefix and isolated question bridge
- **Provider:** native-score-v13 RAM / native-score-v14 disk; native full-state CPU API
- **Control:** switch
- **Parameter scope:** checkpoint_tier0/1; OFF creates no checkpoint; memory budget feature14
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-C-014
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"checkpoint_tier": {"type": "int", "min": 0, "max": 1, "default": 0}}`
- **Experimental:** True

### V7-C-014 — Budget checkpoint scorer CPU

Owns a bounded request-local native CPU full-state checkpoint for exact prefix reuse across alternatives. Cache OFF re-evaluates prefixes. Not GPU KV, cross-request conversation storage or Colibri state.

- **Implementation:** serve/hydra_scoring_runtime.py
- **Entry point:** CPU score, exact prefix and isolated question bridge
- **Provider:** native-score-v13 + llama_state_get_data/set_data
- **Control:** switch
- **Parameter scope:** Checkpoint payload only; original native ConversationCache is a separate engine component
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-H-039
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"max_checkpoint_mib": {"type": "int", "min": 1, "max": 64, "default": 16}}`
- **Experimental:** True

### V7-C-015 — Expert cache slot storage

partial metadata/residency implementation; cache-hit grouped execution not wired; native model pack excluded

- **Implementation:** Strata-main/include/strata/core/expert_cache.hpp
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail; EXPERT_MODEL_INCOMPATIBLE: Bonsai qwen35 has n_expert=0. Local MTP expert pack H2560/FF640/512 experts is not its backbone. Native ExpertDispatch lookup/fill/grouped/output exists for admitted planarQ2 MoE only; no compatible complete backbone/tokenizer/device runtime admitted.; COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED
- **v23 contract:** `{"level": "IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED", "module": "serve/hydra_capability_contracts.py", "dependency": "COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED", "execution_enabled": false}`
- **Experimental:** True

### V7-C-016 — Stato nativo Bonsai

Prism v21 session-local native slot save/erase/restore with model/runtime/session identity, SHA256, disk budget, cancellation and cleanup. CPU continuation restored158337104 bytes and reused22 tokens. GPU also requires a finite grant: native state transfer succeeded but repeated-prefix reuse was0; that mode is refused. Not weight tiering.

- **Implementation:** serve/hydra_native_state.py + serve/hydra_native_text_server.py
- **Entry point:** inspection / blocked activation request
- **Provider:** Prism native slot save/erase/restore
- **Control:** switch
- **Parameter scope:** max_checkpoint_mib1..512; explicit continuation checkpoint only; OFF denies new state operations; identity is request-local; no cross-session import
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"max_checkpoint_mib": {"type": "int", "min": 1, "max": 512, "default": 384}}`
- **v23 contract:** `{"level": "IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED", "module": "serve/hydra_capability_contracts.py", "dependency": null, "execution_enabled": true}`
- **Experimental:** True

### V7-C-017 — Tiering indice Graphify

Owns repository index data only:0 cold/source disk,1 warm/compressed RAM,2 hot/parsed RAM. Source archive re-read and hashed every request. Not model-weight tiering.

- **Implementation:** serve/hydra_graphify_runtime.py
- **Entry point:** Graphify retrieval/context
- **Provider:** GraphIndexTiers
- **Control:** switch
- **Parameter scope:** Repository index residency only; not weights, KV or physical RAM
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-D-026
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"resident_tier": {"type": "int", "min": 0, "max": 2, "default": 2}}`
- **Experimental:** True

### V7-C-018 — Limite commit Windows obbligatorio

Windows process and aggregate Job commit limits:8 GiB for small-model/functional paths,24 GiB for native families. Flags and limits read back before suspended child assignment/resume. Not an RSS or physical-RAM cap; historical peak-accounting discrepancy retained.

- **Implementation:** serve/hydra_execution_v10.py
- **Entry point:** Every exclusive_execute admission
- **Provider:** Windows Job Object PROCESS_MEMORY + JOB_MEMORY
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-C-019 — OOM e recupero controllato

budget/cancellation/error tests with fixtures; no deliberate system OOM

- **Implementation:** Strata-main/serve/hydra_lab_benchmarks.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-D-020 — H0 lexical SQLite retrieval

temporary synthetic authorized corpus, hash/scope; real SQLite reads

- **Implementation:** Strata-main/serve/hydra_graph_memory.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Graph path
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"max_nodes": {"type": "int", "min": 1, "max": 2, "default": 2}}`
- **Experimental:** True

### V7-D-021 — H1 embeddings locali

local CPU encoder and temporary index; provider stopped; historical quality HOLD unchanged

- **Implementation:** HYDRA/hydra_lab/graph_hybrid.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-D-020
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-D-022 — H1 v2 coverage/ranking

real CPU retrieval; coverage contracts tested; historical quality HOLD unchanged

- **Implementation:** HYDRA/hydra_lab/graph_hybrid_v2.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-D-021
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-D-023 — Context Compiler e RequestGuard

real graph context fed to Qwen; native tokenizer, one selected node; guards remaining zero

- **Implementation:** Strata-main/serve/hydra_graph.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-D-020
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-D-024 — Bypass query breve

Ciao uses standard path retrieval_cost_not_justified

- **Implementation:** Strata-main/serve/hydra_graph_optional.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Graph path
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"min_query_chars": {"type": "int", "min": 1, "max": 200, "default": 40}}`
- **Experimental:** True

### V7-D-025 — Provenienza hash scope freshness

test_hydra_graph_memory and optional; tamper/expiry/authorization fixtures

- **Implementation:** Strata-main/serve/hydra_graph_memory.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-D-026 — Graphify — contesto dal repository

Selects current local repository sources for Graph retrieval and Context Compiler; validates source identity and freshness. No GPU/weight acceleration.

- **Implementation:** serve/hydra_graphify_runtime.py
- **Entry point:** /lab/benchmarks/functional; graph chat or retrieval
- **Provider:** Graphify AST candidates + current local source bytes
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'Missing local repository graph: C://Users//Stargate//Desktop//BattleTron-LSC-smartConnect//.diagnostics//publish//hydra-one//graphify-out//graph.json')
- **Dependencies:** V7-D-020
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-D-027 — Snapshot e invalidazione indici

HYDRA graph_hybrid and v2 tests; native CPU integration on new corpus

- **Implementation:** HYDRA/hydra_lab/graph_hybrid.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-E-028 — mmap vs lettura standard

seven native no-mmap samples versus frozen same workload control

- **Implementation:** Strata-main/serve/hydra_v7_experiments.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** Qwen CPU functional path
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-E-029 — Loader modello Windows IOCP

Qwen CPU laboratory only: IOCP delivers actual tensor bytes to llama_file::read_raw in the attested isolated CPU runtime. OFF uses the original reference runtime. Requires mmap OFF; no silent fallback or speedup claim. Applies to new requests after owned cleanup. Bonsai PTQ1_0 CPU uses its separate source-pinned Prism IOCP candidate when its v20 manifest exists; missing candidate fails without fallback. GPU Prism remains standard only. loader_mode:0=IOCP,1=standard reads in the same isolated CPU candidate; both require mmap OFF. Candidate instrumentation is not a speedup claim. V22 prefers source-attested rebuilt CPU candidates for Qwen and Bonsai; changed helper identities fail closed. Rebuild and software checks are not model-loading validation.

- **Implementation:** src/platform/direct_file.cpp + include/hydra/platform/model_reader.hpp
- **Entry point:** Lab.start -> candidate llama_file::read_raw
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** loader_mode0/1; OFF restores reference binary and loader
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'Isolated IOCP CPU runtime not built/attested; no fallback')
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Parameters:** `{"loader_mode": {"type": "int", "min": 0, "max": 1, "default": 0}}`
- **Experimental:** True

### V7-E-030 — Linux O_DIRECT/io_uring

Windows host; Linux-specific branches not hardware tested; io_uring not asserted implemented

- **Implementation:** Strata-main/src/platform/direct_file.cpp
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('UNSUPPORTED', 'Linux-only O_DIRECT/io_uring; Windows environment.')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-E-031 — Prefetch PLE e expert streaming

native large-pack path not admitted; no weight streaming acceleration claimed

- **Implementation:** Strata-main/src/program/generate.cpp
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'PRISM_GRAPH_BUFFER_REBIND_API_REQUIRED')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail; WEIGHT_TIERING_UNSUPPORTED: Prism binds model tensors to long-lived backend buffers for its inference graph; no runtime weight unbind/reload hook. IOCP loads tensor bytes; native slot staging transfers sequence state only. Expert prefetch requires the separate compatible MoE pack and runtime.; PRISM_GRAPH_BUFFER_REBIND_API_REQUIRED
- **v23 contract:** `{"level": "IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED", "module": "serve/hydra_capability_contracts.py", "dependency": "PRISM_GRAPH_BUFFER_REBIND_API_REQUIRED", "execution_enabled": false}`
- **Experimental:** True

### V7-F-032 — Speculative draft/target

no admitted compatible draft-target pair and verified backend integration; no second model started

- **Implementation:** Strata-main/src/program/generate.cpp
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'ATTESTED_DRAFT_TARGET_ADAPTER_REQUIRED')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail; DRAFT_TARGET_INCOMPATIBLE: two local MTP expert blobs have the same SHA256 and belong to a separate H2560 expert layout; no admitted Bonsai qwen35 draft/tokenizer/runtime pair. Identical blobs are not a draft model.; ATTESTED_DRAFT_TARGET_ADAPTER_REQUIRED
- **v23 contract:** `{"level": "IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED", "module": "serve/hydra_capability_contracts.py", "dependency": "ATTESTED_DRAFT_TARGET_ADAPTER_REQUIRED", "execution_enabled": false}`
- **Experimental:** True

### V7-F-033 — Graph capture e acceleratori secondari

native GPU campaigns remain frozen; no supported graph capture test profile admitted

- **Implementation:** Strata-main/serve/hydra_native.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('QUARANTINED', 'GPU graph capture/secondary accelerators not admitted.')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-F-034 — Affinità E-core verificata

Selects up to two allowed group0 E-cores using Windows efficiency classes. Applies and reads back process affinity before child resume. OFF preserves normal adapter affinity; no speedup claimed.

- **Implementation:** serve/hydra_cpu_scheduling.py + serve/hydra_execution_v10.py
- **Entry point:** shared admitted child creation
- **Provider:** Windows CPU-set information + process affinity
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Distinct Windows CPU efficiency classes; allowed group0 E-cores
- **Experimental:** True

### V7-G-035 — Riuso HTTP server testuale CPU

One connection and one in-flight request per native template-aware CPU server. Only fully consumed JSON responses reused; partial/SSE connections discarded. No automatic retry. Connections close at runtime cleanup.

- **Implementation:** serve/hydra_http_pool.py
- **Entry point:** native template-aware CPU adapter; explicit thinking on/off
- **Provider:** SerialConnectionPool
- **Control:** switch
- **Parameter scope:** Bonsai/Huihui/NVFP4 template server only. Qwen HYDRA SSE, scoring C API and TTS retain their existing transports.
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-G-036 — Pipeline distribuita e shard staging

no dedicated remote nodes authorized; production Ubuntu untouched

- **Implementation:** Strata-main/serve/conversation_checkpoint.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail; DEDICATED_NODE_REQUIRED: native RemoteExperts/PeerExperts transport remains source-linked; no authorized remote address, model/pack identity or remote device admission. Localhost software transport does not authorize distributed generation. Production Ubuntu excluded.; AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED
- **v23 contract:** `{"level": "IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED", "module": "serve/hydra_capability_contracts.py", "dependency": "AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED", "execution_enabled": false}`
- **Experimental:** True

### V7-G-037 — Connection loss e timeout trasporto

8 transport tests including controlled errors; no LAN stress

- **Implementation:** Strata-main/serve/test_original_harness_transport.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-H-038 — Text generation app

small Qwen real CPU/Vulkan generation and graph requests

- **Implementation:** Strata-main/serve/hydra_lab_app.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-H-039 — Scoring raw continuazioni

real native CPU scorer; blue/red one token, long two tokens; all scored finite sums/means; child exit0; raw only, no System One parity

- **Implementation:** Strata-main/serve/hydra_lab_app.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-040 — TTS Kokoro

new measured WAV and separate warmup, app registry PASS; old timeout preserved

- **Implementation:** Strata-main/serve/hydra_lab_audio_adapter.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-041 — Vision grounding LocateAnything

real synthetic geometry input and valid bounding boxes; semantic quality limited

- **Implementation:** Strata-main/serve/hydra_lab_native_tasks.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-042 — Image Z-Image Turbo

valid generated PNG 256px two steps; pipeline/backend logs preserved

- **Implementation:** Strata-main/serve/hydra_lab_native_tasks.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('QUARANTINED', 'Image adapter executes Vulkan diffusion even with CPU weight placement.')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-043 — Music YuE2

real short generated WAV and symbolic artifact if emitted; native validation

- **Implementation:** Strata-main/serve/hydra_lab_native_tasks.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-A-001
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-044 — Bridge domande isolato CPU

System One-shaped noul/choice/score requests executed by HYDRA native Qwen CPU scoring. Explicit tokenizer/model provenance. No System One contact, Colibri boundary or semantic parity claim; pinned cache unsupported.

- **Implementation:** serve/hydra_system_one_bridge.py
- **Entry point:** /lab/benchmarks/functional path=/lab/system-one-bridge
- **Provider:** native CPU continuation scorer + bounded question formatter
- **Control:** switch
- **Parameter scope:** 1..4 questions,2..4 alternatives each; no operational System One changes
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-H-045
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-045 — Scoring CPU con prefisso esatto

Native Qwen C API scoring of exact UTF8 prefix plus ordered continuations. No strip, NFC or implicit template. Actual token boundary checked; incompatible continuations return unscorable_boundary. Original fixture-only contract retained separately.

- **Implementation:** serve/hydra_prefix_scoring.py
- **Entry point:** /lab/benchmarks/functional path=/lab/score-prefix
- **Provider:** NativeCPUBackend + existing native_score helper
- **Control:** switch
- **Parameter scope:** prefix<=128 native tokens; full sequence<=256 tokens;1..4 alternatives; no Colibri parity
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Dependencies:** V7-H-039
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-H-046 — Colibri 35B GS64 model

memory and live tokenizer identity/boundary gates remain BLOCKED; no loading

- **Implementation:** Strata-main/serve/colibri_controls.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('BLOCKED', 'FULL35B_RUNTIME_IDENTITY_AND_MEMORY_MANIFEST_REQUIRED')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail; COLIBRI_NOT_ADMITTED: require exact installed-runtime/tokenizer parity, full35B asset identity and model-plus-state/workspace memory upper bound. Tokenizer-only probe and smaller task outputs do not authorize the full model.; FULL35B_RUNTIME_IDENTITY_AND_MEMORY_MANIFEST_REQUIRED
- **v23 contract:** `{"level": "IMPLEMENTED_SOFTWARE_CONTRACT; HARDWARE_NOT_VERIFIED", "module": "serve/hydra_capability_contracts.py", "dependency": "FULL35B_RUNTIME_IDENTITY_AND_MEMORY_MANIFEST_REQUIRED", "execution_enabled": false}`
- **Experimental:** True

### V7-I-047 — Exclusive lock e reservation

cross-workspace lease, cancellation and admission tests; real serial runs cleanup

- **Implementation:** Strata-main/serve/hydra_lab_benchmarks.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-I-048 — Cancellation e timeout child

controlled child/fixture tests; old failures retained; no global process-name termination

- **Implementation:** HYDRA/hydra_lab/managed.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-I-049 — Publication after cleanup

RED 3 failures then GREEN; native Locate post-fix verification; shared runner/audio fixed too

- **Implementation:** Strata-main/serve/hydra_lab_native_tasks.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-I-050 — Execution identity e immutable events

identity and registry tests; previous rows checked canonical digest

- **Implementation:** HYDRA/hydra_lab/execution_identity.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-I-051 — Routing/planner research variants

baseline, causal, mixed, one research suites; not native generation acceleration

- **Implementation:** HYDRA/hydra_lab/research.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** request_only
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Gate:** ('UNSUPPORTED', 'Routing/planner research variants are software-only; no new runtime dispatcher.')
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** True

### V7-J-052 — Benchmark persistent history/export

owned app restart verified records; actual SQLite JSON/CSV export

- **Implementation:** Strata-main/serve/hydra_lab_integration.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-J-053 — Monitor live feed

real runner feed producer and software integration; browser visual check unavailable

- **Implementation:** Strata-main/serve/hydra_lab_live.py
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-J-054 — Grafici delle prestazioni

Controls optional charts in the existing page. Safety controls and history remain available.

- **Implementation:** Strata-main/serve/web/performance-hydra-registry.js
- **Entry point:** shared admitted lab resolver
- **Provider:** source-linked v11 laboratory implementation
- **Control:** switch
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-J-055 — Catalog asset/runtime compatibility

catalog evidence state independent of CANCELLED/metadata failure; 16 identities retained

- **Implementation:** Strata-main/serve/hydra_lab_benchmarks.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### V7-J-056 — Lab OFF isolamento operativo

opt-in contracts; no startup/default/router/System One modifications

- **Implementation:** Strata-main/serve/hydra_lab_integration.py
- **Entry point:** inspection / blocked activation request
- **Provider:** source-linked v11 laboratory implementation
- **Control:** mandatory
- **Parameter scope:** No configurable runtime parameters
- **Build status:** SOURCE_PRESENT; see v11 target manifest
- **Prerequisites:** Exclusive coordinator and verified cleanup; Asset/runtime hashes verified at admission; CPU RAM >=12 GiB; per-adapter stricter budgets prevail
- **Experimental:** False

### runtime.vulkan — Backend VULKAN

ErrorDeviceLost cause UNKNOWN; GPU quarantine

- **Implementation:** serve/hydra_execution_v10.py
- **Entry point:** quarantined GPU admission
- **Provider:** vulkan
- **Control:** request_only
- **Parameter scope:** No GPU parameters applied while quarantined
- **Build status:** RUNTIME_HISTORICAL
- **Gate:** ('QUARANTINED', 'ErrorDeviceLost cause UNKNOWN; GPU quarantine')
- **Prerequisites:** Distinct authorized GPU recovery gate
- **Experimental:** True

### runtime.hip — Backend HIP

HIP compiled, GPU inference not admitted

- **Implementation:** serve/hydra_execution_v10.py
- **Entry point:** quarantined GPU admission
- **Provider:** hip
- **Control:** request_only
- **Parameter scope:** No GPU parameters applied while quarantined
- **Build status:** COMPILED_NOT_EXECUTED
- **Gate:** ('QUARANTINED', 'HIP compiled, GPU inference not admitted')
- **Prerequisites:** Distinct authorized GPU recovery gate
- **Experimental:** True

### runtime.cuda — Backend CUDA

CUDA toolkit nvcc unavailable; GPU quarantine

- **Implementation:** serve/hydra_execution_v10.py
- **Entry point:** quarantined GPU admission
- **Provider:** cuda
- **Control:** request_only
- **Parameter scope:** No GPU parameters applied while quarantined
- **Build status:** TOOLCHAIN_MISSING
- **Gate:** ('QUARANTINED', 'CUDA toolkit nvcc unavailable; GPU quarantine')
- **Prerequisites:** Distinct authorized GPU recovery gate
- **Experimental:** True
