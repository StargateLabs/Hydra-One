<p align="center"><img src="assets/hero.svg" alt="Hydra One — logo originale e laboratorio Stargate Labs" width="1280"></p>

# Hydra One

**Inferenza ibrida. Modelli locali. Un laboratorio sotto controllo.**

[Italiano](README.md) · [English](README.en.md) · [Installazione](docs/INSTALL.it.md) · [Funzionalità](docs/FEATURES.md) · [Crediti](docs/CREDITS.it.md)

[![Beta](https://img.shields.io/badge/status-beta-16c9e8?style=flat-square)](docs/FEATURES.md) [![License](https://img.shields.io/badge/license-MIT-8faac0?style=flat-square)](LICENSE) [![Stars](https://img.shields.io/github/stars/StargateLabs/Hydra-One?style=flat-square&color=16c9e8)](https://github.com/StargateLabs/Hydra-One/stargazers)

<!-- logo-directory:start -->

## Le app e gli strumenti del nostro workspace

<p align="center"><img src="assets/app-gallery.svg" alt="Hydra One — original application logos in centered, evenly spaced cards" width="1280"></p>

<!-- logo-directory:end -->


Hydra One è la versione beta sviluppata da **Stargate Labs** a partire da Strata. Unisce la nostra integrazione HYDRA One, un workspace web per i modelli locali e strumenti per osservare, misurare e controllare l’esecuzione. Questa pubblicazione deriva dai **nostri sorgenti locali modificati**, con base nativa 0.1.38; non è una copia dell’attuale ramo principale upstream.

<details>
<summary><strong>App integrate: loghi, funzioni e autori</strong> — apri i dettagli</summary>

Le integrazioni sono descritte qui nella pagina principale. Ciascuna mantiene requisiti, licenza e capacità del proprio runtime; la presenza dell’adattatore non significa parità con tutta l’app originale.

| Logo | App / Source | Il suo ruolo nella nostra mod | Autori e ringraziamenti |
|---|---|---|---|
| <img src="serve/web/brand-llama.cpp.svg" alt="llama.cpp" width="52" height="52"> | **[llama.cpp](https://github.com/ggml-org/llama.cpp)** | GGUF engine, native libraries, format tooling and optional server transport. | ggml authors and contributors |
| <img src="serve/web/brand-unsloth-symbol.png" alt="Unsloth" width="52" height="52"> | **[Unsloth](https://github.com/unslothai/unsloth)** | Selected Python environment, inference/QLoRA integration and owned Studio service. | Unsloth team and contributors |
| <img src="serve/web/brand-transformers.svg" alt="Transformers" width="52" height="52"> | **[Transformers](https://github.com/huggingface/transformers)** | Local Safetensors text/vision runtime and model metadata integration. | Hugging Face and contributors |
| <img src="serve/web/brand-pytorch.svg" alt="PyTorch" width="52" height="52"> | **[PyTorch](https://github.com/pytorch/pytorch)** | Tensor execution, device/runtime integration and training dependencies. | PyTorch contributors |
| <img src="serve/web/brand-airllm.png" alt="AirLLM" width="52" height="52"> | **[AirLLM](https://github.com/lyogavin/airllm)** | Optional local layer-streaming backend and isolated runtime selection. | lyogavin and AirLLM contributors |
| <img src="serve/web/brand-colibri.svg" alt="Colibri" width="52" height="52"> | **[Colibri](https://github.com/JustVugg/colibri)** | Isolated engine launcher, controls, model routing and System One integration. | JustVugg and Colibri contributors |
| <img src="serve/web/brand-soup.png" alt="Soup" width="52" height="52"> | **[Soup](https://github.com/MakazhanAlpamys/Soup)** | Bundled planning modules and managed training integration; original Apache notices retained. | Makazhan Alpamys / Soup Team |
| <img src="serve/web/brand-whisper.cpp.jpeg" alt="Whisper.cpp" width="52" height="52"> | **[Whisper.cpp](https://github.com/ggml-org/whisper.cpp)** | Local ASR and translation. Selected distributions also use the credited Unsloth fork. | ggml authors and Whisper.cpp contributors |
| <img src="serve/web/brand-unsloth-symbol.png" alt="audio.cpp" width="52" height="52"> | **[audio.cpp](https://github.com/unslothai/audio.cpp)** | Selected local speech runtime. Displayed mark identifies Unsloth, not a separate audio.cpp logo. | Unsloth distribution and upstream contributors |
| <img src="serve/web/brand-voicestudio.png" alt="VoiceStudio" width="52" height="52"> | **[VoiceStudio](https://github.com/debpalash/VoiceStudio)** | Local API/MCP integration, jobs, profiles and rendering workflows. | debpalash and VoiceStudio contributors |
| <img src="serve/web/brand-myshell-original.svg" alt="OpenVoice" width="52" height="52"> | **[OpenVoice](https://github.com/myshell-ai/OpenVoice)** | Optional voice-conversion model/runtime path; task-specific asset checks. | MyShell and OpenVoice contributors |
| <img src="serve/web/brand-meta-audio.svg" alt="AudioCraft" width="52" height="52"> | **[AudioCraft](https://github.com/facebookresearch/audiocraft)** | Music and audio generation, conditioning and training adapters. | Meta / AudioCraft contributors |
| <img src="serve/web/brand-openwebui.svg" alt="Open WebUI" width="52" height="52"> | **[Open WebUI](https://github.com/open-webui/open-webui)** | Original document/OCR/retrieval workers reused by our local adapter; no second dashboard claimed. | Open WebUI contributors |
| <img src="serve/web/harness-logo-opencode.svg" alt="OpenCode" width="52" height="52"> | **[OpenCode](https://github.com/anomalyco/opencode)** | Original harness transport, workspace/session integration and candidate updates. | Anomaly and OpenCode contributors |
| <img src="serve/web/harness-logo-dsh.svg" alt="DeepSeek Harness" width="52" height="52"> | **[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)** | Original harness integration and official package/version mapping. | DeepSeek and harness contributors |
| <img src="serve/web/harness-logo-trueforge.svg" alt="TrueForge" width="52" height="52"> | **[TrueForge](https://github.com/truefoundry/trueforge)** | Harness integration with shared browser/memory services and candidate management. | TrueFoundry and contributors |
| <img src="serve/web/harness-logo-hermes.svg" alt="Hermes Agent" width="52" height="52"> | **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** | Original agent integration, project services and isolated source candidate workflow. | Nous Research and contributors |
| <img src="serve/web/harness-logo-claude.png" alt="Claude Code" width="52" height="52"> | **[Claude Code](https://github.com/anthropics/claude-code)** | Native CLI/harness integration and signed official candidate checks; no claim to redistribute its implementation. | Anthropic |
| <img src="serve/web/brand-browser.svg" alt="Playwright" width="52" height="52"> | **[Playwright](https://github.com/microsoft/playwright-mcp)** | Shared MCP browser service and verified candidate activation. | Microsoft and Playwright contributors |
| <img src="serve/web/brand-memory.svg" alt="MCP memory" width="52" height="52"> | **[MCP memory](https://github.com/modelcontextprotocol/servers)** | Shared memory-server contract and project-scoped MCP configuration. | Model Context Protocol contributors |
| Headroom | **[Headroom](https://github.com/headroomlabs-ai/headroom)** | Project-scoped routing metadata, runtime contract and MCP integration. | Headroom Labs and contributors |


<!-- user-capabilities:start -->

</details>

## Un progetto personale, condiviso

Hydra One nasce dalle mie esigenze e dal mio modo di lavorare con l’intelligenza artificiale locale. Le scelte, le integrazioni e le funzioni riflettono le mie priorità: possono incontrare le preferenze di altri utenti oppure rispondere a necessità diverse dalle loro. Ho scelto di condividere questo progetto per rendere disponibile il lavoro svolto, favorire il confronto e offrire una base utile a chi desidera esplorarla o adattarla alle proprie esigenze.

<details>
<summary><strong>Cosa puoi fare con Hydra One</strong> — apri i dettagli</summary>

La mod riunisce questi flussi nello stesso workspace. Le operazioni richiedono i modelli, i runtime e le capacità indicati: la beta non li dichiara tutti già installati o universalmente validati.

### Modelli e chat

**Caricare un modello locale** — Scegli un GGUF o un checkpoint Safetensors, controlla il motore richiesto e avvia il percorso compatibile. I pack nativi e i formati Prism mantengono i propri adapter. [Implementazione / Source](serve/optional_backends.py)

**Aprire la dashboard senza caricare i pesi** — L’avvio lazy rende disponibile l’interfaccia prima del modello; puoi consultare i pannelli e scegliere quando avviare l’inferenza. [Implementazione / Source](serve/server.py)

**Lavorare con motori diversi nello stesso workspace** — Usa gli adapter HYDRA, il motore nativo, llama.cpp, Transformers/PEFT, Unsloth, AirLLM, Colibri o un’API locale compatibile, in base alle dipendenze disponibili. [Implementazione / Source](serve/optional_backends.py)

**Conversare e organizzare il lavoro** — Usa chat, cronologia e archivio; conserva conversazioni e metadati di organizzazione nell’interfaccia esistente, senza creare una seconda chat parallela. [Implementazione / Source](serve/web/app.js)

**Collegare altre applicazioni alla tua API locale** — Il server espone percorsi compatibili OpenAI e Anthropic per collegare client esterni; gli output strutturati passano da validazione esplicita. [Implementazione / Source](serve/structured.py)

### Cataloghi LLM

**Cercare modelli e confrontare pubblicazioni** — Sfoglia categorie, autori, versioni, varianti e file. Leggi model card, base model e licenza prima di scegliere cosa installare. [Implementazione / Source](serve/optional_catalogue.py)

**Ritrovare modelli già presenti sul disco** — L’inventario locale cerca nelle radici configurate e nelle cache note, distingue i ruoli dei file e riconosce i modelli suddivisi in più parti. [Implementazione / Source](serve/local_model_discovery.py)

**Scaricare e importare asset selezionati** — Usa download con progressi in byte, gestione delle parti e import locali. Disponibilità, spazio e condizioni di accesso rimangono requisiti da verificare. [Implementazione / Source](serve/studio_model_download.py)

### Agenti e strumenti

**Usare agenti e coding tool integrati** — Il workspace collega OpenCode, DeepSeek Harness, TrueForge, Hermes e Claude Code ai rispettivi percorsi originali, con gestione delle sessioni e dei candidati. [Implementazione / Source](serve/original_harness_routes.py)

**Dare strumenti MCP alla chat** — Collega servizi MCP configurati e usa i servizi condivisi browser/memoria. Il tool calling resta dipendente dalle capacità del modello selezionato. [Implementazione / Source](serve/mcp.py)

**Consultare prompt e skill** — La biblioteca dell’interfaccia riunisce prompt e skill consultabili nel workspace. La loro presenza non significa che ogni contenuto importato sia un nuovo componente nativo di Hydra. [Implementazione / Source](serve/web/index.html)

### Documenti e memoria

**Portare documenti nella chat** — Importa PDF, DOCX e testi attraverso il percorso documenti; usa estrazione e OCR quando il runtime e i pesi locali sono disponibili. [Implementazione / Source](serve/open_webui_runtime.py)

**Cercare passaggi e verificarne la provenienza** — Organizza raccolte, cerca nella libreria e conserva nome del documento, pagina e posizione. BM25, semantica e fusione ibrida hanno prerequisiti distinti. [Implementazione / Source](serve/open_webui_runtime.py)

**Gestire il contesto con HYDRA** — Usa i percorsi H0/H1/H1v2, grafo locale, hash delle fonti e budget del contesto. Le fonti modificate o fuori perimetro vengono gestite dai controlli di ammissione. [Implementazione / Source](serve/hydra_graph_memory.py)

### Training e modelli

**Addestrare adattatori LoRA** — Prepara dataset e parametri espliciti per il training locale; runner, dispositivo, checkpoint e destinazione degli export vengono validati. [Implementazione / Source](serve/local_training.py)

**Sperimentare metodi di fine-tuning** — Il codice espone opzioni SFT, DPO, GRPO, KTO, reward e VLM, con restrizioni per runner e dispositivo; non sono tutti percorsi GPU intercambiabili. [Implementazione / Source](serve/training_options.py)

**Convertire ed esportare modelli** — La conversione GGUF è un lavoro posseduto e annullabile, con risultati persistiti e destinazioni controllate. [Implementazione / Source](serve/local_export.py)

### Voce e audio

**Trascrivere e tradurre audio** — Whisper locale espone impostazioni di decodifica e lingua, segmenti e sottotitoli, usando il modello e il runtime installati. [Implementazione / Source](serve/local_audio.py)

**Generare voce da testo** — Usa il runtime audio.cpp selezionato e i percorsi TTS supportati; il laboratorio include un adapter Kokoro distinto dal caricamento dei modelli chat. [Implementazione / Source](serve/local_speech.py)

**Gestire produzioni vocali** — VoiceStudio collega API/MCP, profili, job e rendering; libreria ed editing audio sono moduli dedicati del workspace. [Implementazione / Source](serve/voicestudio.py)

**Lavorare su musica e separazione** — AudioCraft e i worker generativi gestiscono i task registrati con modelli e conditioning compatibili; la separazione audio ha un percorso dedicato. [Implementazione / Source](serve/local_generative_audio.py)

### Immagini e video

**Usare modelli vision nella chat** — Associa un projector GGUF valido o il percorso Transformers vision appropriato. Le capacità dichiarate dal backend determinano l’accettazione degli input. [Implementazione / Source](serve/local_vision.py)

**Generare immagini e video localmente** — I worker Diffusers coprono famiglie esplicite Stable Diffusion, SDXL, inpainting e video. Servono pipeline, pesi e risorse compatibili. [Implementazione / Source](serve/local_visual_generation.py)

### Prestazioni e Benchmark

**Misurare il modello con un protocollo** — Configura ripetizioni, riscaldamento, prompt e budget token. Registra campioni reali, annulla un job e conserva gli esiti nel banco di lavoro. [Implementazione / Source](serve/optional_benchmark.py)

**Confrontare configurazioni senza falsare le metriche** — Confronta rapporti coerenti e identità dei modelli; separa HTTP, TTFT, decode e prefill. Usa archivio, filtri, grafici ed export CSV per leggere i risultati. [Implementazione / Source](serve/benchmark_comparison.py)

**Valutare alternative con System One** — Il workspace Colibri e i contratti HYDRA distinguono scelta, sì/no, punteggio e scoring dei prefissi. Percorsi e prove non sono dichiarati equivalenti senza una verifica dedicata. [Implementazione / Source](serve/colibri_controls.py)

**Controllare le funzioni sperimentali** — Ispeziona i 59 controlli, dipendenze e parametri; prepara modifiche versionate e mantieni i blocchi per hardware o runtime mancanti. [Implementazione / Source](serve/hydra_feature_control.py)

### Gestione del sistema

**Osservare carichi e ciclo di vita** — Monitor e registri distinguono attività del backend, telemetria del PC e prove storiche. Prenotazioni, annullamento, arresto e idle unload gestiscono i processi posseduti. [Implementazione / Source](serve/process_lifecycle.py)

**Aggiornare conservando la mod** — Controlla fonti e versioni, prepara candidati isolati, verifica dipendenze e seleziona o ripristina i percorsi supportati senza confondere download e attivazione. [Implementazione / Source](serve/update_center.py)

**Salvare e recuperare il lavoro** — I backup verificano gli hash dei sorgenti editabili. Il recupero HYDRA ripristina soltanto file mancanti e conserva quelli esistenti modificati. [Implementazione / Source](serve/customization_backup.py)

<!-- user-capabilities:end -->

</details>

## Piattaforma Local AI all-in-one

| Area | Cosa contiene questa versione | Sorgente |
|---|---|---|
| HYDRA One | Controller ibrido, budget di memoria, pianificazione, sidecar e monitoraggio | [Motore Python](hydra-engine/python/) · [integrazione](serve/hydra_one.py) |
| Runtime nativo | Ciclo di vita posseduto, controllo ammissione, generazione e scoring CPU | [Adapter](serve/hydra_native.py) · [loader](serve/hydra_native_text_server.py) |
| Laboratorio | 56 funzioni censite, controlli versionati, dipendenze e blocchi espliciti | [Registro completo](docs/FEATURES.md) |
| Memoria e retrieval | Grafo locale, H0/H1/H1v2, provenienza delle fonti e budget del contesto | [Graph memory](serve/hydra_graph_memory.py) |
| Modelli e backend | Catalogo Hugging Face, GGUF/Safetensors e integrazioni opzionali | [Catalogo](serve/catalogue.py) · [backend](serve/optional_backends.py) |
| Workspace | Chat, MCP, monitor, benchmark e gestione dei componenti | [Interfaccia](serve/web/index.html) · [server](serve/server.py) |


<p align="center"><img src="assets/ecosystem.svg" alt="Hydra One — inference, agents, training, multimodal, knowledge and engineering ecosystem" width="1280"></p>

## La nostra integrazione all-in-one

Il progetto riunisce lavoro su inferenza, chat, agenti, MCP, training e produzione multimodale. La guida completa distingue ogni tipo di integrazione e collega i sorgenti che la implementano.

| Area | Componenti e lavoro incluso |
|---|---|
| **Inference** | HYDRA One · native C++/CUDA/HIP · llama.cpp · Prism · Transformers/PEFT · Unsloth · AirLLM · Colibri · local APIs |
| **Agents / apps** | OpenCode · DeepSeek Harness · TrueForge · Hermes · Claude Code · native Claude/Antigravity workspace |
| **Tools / memory** | MCP · Playwright browser · shared memory · Headroom · local graph · H0/H1/H1v2 · source provenance |
| **Training** | LoRA · SFT · DPO · GRPO · KTO · reward · VLM · TRL CPU · Soup · Unsloth QLoRA · checkpoints · GGUF export |
| **Multimodal** | Whisper ASR · audio.cpp / Kokoro TTS · VoiceStudio · AudioCraft · source separation · Diffusers image/video · vision projectors |
| **Workspace services** | Open WebUI document/OCR/semantic/reranker workers · model catalogue · downloads/imports · component staging/rollback · telemetry |
| **Research / beta** | 56 baseline experimental features + 3 GPU controls · admission · CPU scheduling · IOCP · scoring · tiering contracts · benchmark history |

**[Platform guide / Guida completa](docs/PLATFORM.it.md)** · [Every source module / Tutti i moduli](docs/MODULES.md) · [Experimental register / Registro sperimentale](docs/FEATURES.md)

Queste sono integrazioni e percorsi presenti nel codice: per installazione, requisiti e blocchi di ogni componente consulta la guida. Il supporto dei modelli dipende da architettura, formato, runtime e risorse; non dichiariamo compatibilità universale non verificata.

## Il banco di lavoro e i servizi della mod

### [Prestazioni e Benchmark](docs/WORKBENCH.it.md)

Prestazioni e Benchmark sono il banco di lavoro con cui osserviamo i modelli e valutiamo i potenziamenti della mod. La prima sezione raccoglie e rende leggibili le misure; la seconda prepara ed esegue le prove sul motore selezionato. Il legame tra le due non è una classifica promozionale: serve a ricondurre un risultato al modello, al runtime, al protocollo e alla configurazione che lo hanno prodotto. Un cambiamento di cache, contesto, thread o backend deve essere confrontato con una prova coerente, non con un numero appartenente a un modello diverso.

### [Cataloghi LLM e compatibilità](docs/CATALOGUES.it.md)

La mod non tratta ogni risultato di ricerca come un modello eseguibile. I cataloghi collegano ricerca Hugging Face, metadati delle pubblicazioni, varianti, file, modelli locali e compatibilità dei runtime. Il percorso nativo e il catalogo opzionale hanno criteri diversi: un pack esperti del motore nativo non deve essere avviato come GGUF generico, e un formato Prism non deve essere inoltrato silenziosamente a un runtime incompatibile.

### [Aggiornamenti, backup e recupero](docs/UPDATES.it.md)

Il Centro aggiornamenti non è soltanto un elenco di versioni: collega inventario degli ambienti, fonti ufficiali, download verificati, candidati isolati, validazione e selezione dei componenti. L’obiettivo del nostro adattatore è preservare configurazioni, sorgenti modificati e dati mentre evolve la base dei motori e delle app. Versione disponibile, pacchetto scaricato, candidato validato e runtime attivo sono stati diversi e devono rimanere distinguibili.

<!-- integrated-platform:start -->

<details>
<summary><strong>Tutti i percorsi di inferenza e generazione</strong> — apri i dettagli</summary>

| Engine | Ruolo e implementazione | Requisiti e vincoli |
|---|---|---|
| <p align="center"><img src="assets/hydra-one.png" alt="HYDRA One" width="56"><br><b>HYDRA One</b></p> | Controller ibrido / Hybrid controller. Planning, budgets, sidecar, storage identity, lifecycle and graph integration. [Source](serve/hydra_one.py) | Backend-owned model residency; not a replacement tensor executor. |
| <p align="center"><img src="assets/hydra-one.png" alt="Native engine" width="56"><br><b>Native engine</b></p> | C++ / CUDA / HIP. Native model packs, expert execution, cache, speculative paths and CPU/GPU work sharing. [Source](CMakeLists.txt) | Model-pack and toolchain specific; upstream measurements remain attributed. |
| <p align="center"><img src="serve/web/brand-llama.cpp.svg" alt="llama.cpp" width="56"><br><b>llama.cpp</b></p> | GGUF + local API. Owned server process, split GGUF handling, configuration, model discovery and request transport. [Source](serve/optional_backends.py) | Architecture, quantization and installed runtime must match. |
| **Prism llama.cpp**<br><sub>Specialized runtime; no separate verified logo</sub> | Specialized GGUF. Pinned Prism loader source, model-family checks and isolated native candidate. [Source](serve/gguf_runtime_compatibility.py) | Distinct runtime for compatible Prism formats; no silent generic fallback. |
| <p align="center"><img src="serve/web/brand-transformers.svg" alt="Transformers / PEFT" width="56"><br><b>Transformers / PEFT</b></p> | Safetensors + LoRA. Owned Python text inference, CPU FP32, device-specific GPU paths, local adapters and thread controls. [Source](serve/safetensors_runtime.py) | Dependencies and model class required; GPU admission is gated separately. |
| <p align="center"><img src="serve/web/brand-unsloth-symbol.png" alt="Unsloth" width="56"><br><b>Unsloth</b></p> | Inference / QLoRA / Studio. Python backend integration, native Studio service ownership and candidate update handling. [Source](serve/unsloth_workspace.py) | Installed Unsloth environment required; upstream authentication and frame policy preserved. |
| <p align="center"><img src="serve/web/brand-airllm.png" alt="AirLLM" width="56"><br><b>AirLLM</b></p> | Layer streaming. Project runtime selection and CPU disk-backed layer-streaming integration. [Source](serve/airllm_runtime.py) | Compatible model and runtime needed; disk streaming is not a guaranteed speedup. |
| <p align="center"><img src="serve/web/brand-colibri.svg" alt="Colibri" width="56"><br><b>Colibri</b></p> | Isolated optional engine. Official isolated launcher, controls, local endpoint validation and component updates. [Source](serve/colibri_workspace.py) | Full model assets and matching runtime required; catalogue listing is not successful inference. |
| <p align="center"><img src="serve/web/brand-soup.png" alt="Soup" width="56"><br><b>Soup</b></p> | Training integration. Bundled upstream planning modules, isolated package selection and training runners. [Source](serve/soup_runtime.py) | CPU/native/GPU runner restrictions are enforced by training options. |
| **Local API**<br><sub>API transport</sub> | OpenAI-compatible transport. Attach compatible local model APIs, normalize messages, tools and response handling. [Source](serve/optional_inference.py) | Capabilities are reported by the selected model/API; tools and vision are not assumed. |
| <p align="center"><img src="serve/web/brand-whisper.cpp.jpeg" alt="Whisper.cpp" width="56"><br><b>Whisper.cpp</b></p> | ASR / translation. Owned local transcription, language controls, decoding parameters, segments and subtitles. [Source](serve/local_audio.py) | Whisper model and selected binary required. |
| <p align="center"><img src="serve/web/brand-unsloth-symbol.png" alt="audio.cpp / Kokoro" width="56"><br><b>audio.cpp / Kokoro</b></p> | Text-to-speech. Local CPU speech and an explicit Kokoro laboratory adapter. [Source](serve/local_speech.py) | Registered speech model/runtime required; separate from a chat-model loader. |
| <p align="center"><img src="serve/web/brand-transformers.svg" alt="Diffusers" width="56"><br><b>Diffusers</b></p> | Images / video. Explicit Stable Diffusion, SDXL, inpainting, Stable Video Diffusion and TextToVideoSD worker families. [Source](serve/local_visual_generation.py) | Only implemented pipeline families and installed models; no universal media support. |
| <p align="center"><img src="serve/web/brand-meta-audio.svg" alt="AudioCraft / audio workers" width="56"><br><b>AudioCraft / audio workers</b></p> | Music / effects / voice. Conditioning, native integration, local generation and managed audio workflows. [Source](serve/local_generative_audio.py) | Task-specific assets, conditioning and runtime required. |

</details>

<details>
<summary><strong>Funzioni del workspace, area per area</strong> — apri i dettagli</summary>

### Agents and coding

OpenCode, DeepSeek Harness, TrueForge, Hermes Agent and Claude Code component maps; original transport, sessions and update candidates.

[harness_updates](serve/harness_updates.py) · [original_harness_transport](serve/original_harness_transport.py) · [original_harness_routes](serve/original_harness_routes.py) · [hermes_integration](serve/hermes_integration.py)

### Native workspace

Dashboard, Claude and Antigravity workspace kinds; owned native host and local URL validation.

[native_workspace](serve/native_workspace.py) · [native_window_host](serve/native_window_host.py) · [native_workspace_routes](serve/native_workspace_routes.py)

### MCP and tools

Project MCP configuration, chat tool bridge, shared browser/memory services and controlled candidate activation.

[mcp](serve/mcp.py) · [project_mcp](serve/project_mcp.py) · [shared_agent_services](serve/shared_agent_services.py) · [optional_tools](serve/optional_tools.py)

### Browser and memory services

Playwright MCP and MCP memory server integrated through the shared service configuration.

[trueforge_setup](serve/trueforge_setup.py) · [shared_agent_services](serve/shared_agent_services.py)

### Headroom

Project-scoped runtime metadata, routing enablement and MCP launch contract.

[headroom_integration](serve/headroom_integration.py)

### Open WebUI functions

Document import, local workers for OCR, semantic processing and reranking. Existing module states no separate Open WebUI HTTP server/UI.

[open_webui_runtime](serve/open_webui_runtime.py) · [open_webui_ocr_worker](serve/open_webui_ocr_worker.py) · [open_webui_semantic_worker](serve/open_webui_semantic_worker.py) · [open_webui_reranker_worker](serve/open_webui_reranker_worker.py)

### Model library

HF search, author/model-card metadata, categories, local discovery, split-file identity, imports and byte-level download progress.

[optional_catalogue](serve/optional_catalogue.py) · [local_model_discovery](serve/local_model_discovery.py) · [studio_model_download](serve/studio_model_download.py) · [studio_model_import](serve/studio_model_import.py) · [gguf_parts](serve/gguf_parts.py)

### Fine-tuning

LoRA, explicit SFT/DPO/GRPO/KTO/reward/VLM options; CPU TRL, Soup and Unsloth QLoRA runner policies; checkpoint validation.

[local_training](serve/local_training.py) · [training_options](serve/training_options.py) · [advanced_training_runtime](serve/advanced_training_runtime.py) · [vlm_training_runtime](serve/vlm_training_runtime.py)

### Export and datasets

Owned cancellable GGUF conversion, dataset upload, output validation and checkpoint/resume handling.

[local_export](serve/local_export.py) · [vision_dataset_upload](serve/vision_dataset_upload.py) · [train_local_lora](tools/train_local_lora.py)

### Vision

GGUF projector pairing, CPU default and capability-checked GPU offload; Transformers vision paths and multimodal capability reporting.

[local_vision](serve/local_vision.py) · [transformers_vision](serve/transformers_vision.py) · [multimedia_capabilities](serve/multimedia_capabilities.py)

### Voice production

VoiceStudio jobs/profiles/rendering, local speech, audio library/editing and audiobook planning tests.

[voicestudio](serve/voicestudio.py) · [voicestudio_jobs](serve/voicestudio_jobs.py) · [voicestudio_profiles](serve/voicestudio_profiles.py) · [voicestudio_render](serve/voicestudio_render.py) · [audio_library](serve/audio_library.py) · [audio_edit](serve/audio_edit.py)

### Music and audio

AudioCraft conditioning and training, local generative audio, source separation and task-specific capability checks.

[audiocraft_native](serve/audiocraft_native.py) · [audiocraft_conditioning](serve/audiocraft_conditioning.py) · [audiocraft_training](serve/audiocraft_training.py) · [local_generative_audio](serve/local_generative_audio.py) · [local_separation](serve/local_separation.py)

### Graph and retrieval

Explicit local corpus; SQLite memory, H0/H1/H1v2 graph paths, exact frontend/template reuse, source hashes, freshness and context guards.

[hydra_graph_memory](serve/hydra_graph_memory.py) · [hydra_graph_optional](serve/hydra_graph_optional.py) · [hydra_graphify_runtime](serve/hydra_graphify_runtime.py) · [hydra_graph](serve/hydra_graph.py)

### Laboratory and experiments

56 baseline features plus separate GPU controls; dependency resolution, preview/apply/rollback, execution admission and historical evidence.

[hydra_feature_control](serve/hydra_feature_control.py) · [hydra_lab_app](serve/hydra_lab_app.py) · [hydra_lab_benchmarks](serve/hydra_lab_benchmarks.py) · [hydra_capability_contracts](serve/hydra_capability_contracts.py)

### Native performance research

IOCP source consumer, CPU scheduling, bounded request-local checkpoints, raw scoring, System One bridge contracts and blocked hardware-dependent paths.

[direct_file](src/platform/direct_file.cpp) · [hydra_cpu_scheduling](serve/hydra_cpu_scheduling.py) · [hydra_scoring_runtime](serve/hydra_scoring_runtime.py) · [hydra_system_one_bridge](serve/hydra_system_one_bridge.py)

### Metrics and verification

Run history, timing, model/runtime identity, live monitoring, source provenance and explicit task-completion contracts.

[instrumentation](serve/instrumentation.py) · [verification_history](serve/verification_history.py) · [hydra_task_completion](serve/hydra_task_completion.py) · [hydra_lab_live](serve/hydra_lab_live.py)

### Process and resource control

Owned children, exclusive GPU leases, cancellation, graceful shutdown, idle unloading and Windows Job limits.

[process_lifecycle](serve/process_lifecycle.py) · [gpu_lease](serve/gpu_lease.py) · [native_graceful_shutdown](serve/native_graceful_shutdown.py) · [winjob](serve/winjob.py)

### Updates and recovery

Official source checks, candidate staging, source fingerprints, explicit activation/rollback, dependency supervision and source-only recovery capsule.

[update_center](serve/update_center.py) · [safe_update](serve/safe_update.py) · [dependency_supervisor](serve/dependency_supervisor.py) · [hydra_recovery](serve/hydra_recovery.py)

### APIs and output

OpenAI/Anthropic-compatible server routes, structured response validation, request monitoring and model lifecycle routes.

[server](serve/server.py) · [structured](serve/structured.py) · [model_engine_routes](serve/model_engine_routes.py)

</details>

<details>
<summary><strong>Registro completo dei controlli sperimentali</strong> — apri i dettagli</summary>

56 funzioni di base e 3 controlli GPU separati. Sono riportati lo stato del controllo e i blocchi attuali; non sono una certificazione hardware né una promessa di supporto di ogni modello.

| ID | Funzione e implementazione | Controllo / vincolo attuale |
|---|---|---|
| `V7-A-001` | **Backend CPU**<br>Historical CPU/Vulkan group reconciled: this control gates CPU; GPU backends have separate quarantined controls. | switch<br>Admission and runtime prerequisites apply |
| `V7-A-002` | **Offload parziale/completo e device**<br>native runtime logs and buffer allocations; CPU and Vulkan paths | switch<br>QUARANTINED / Partial/full GPU offload and device selection require the separate GPU recovery gate. |
| `V7-A-003` | **Riuso runtime nel benchmark CPU**<br>Qwen CPU normal runner:ON keeps one owned runtime across warmup/samples;OFF closes it after each request and reloads serially. Lock remains held through final cleanup. No resident model across independent admissions. | switch<br>Admission and runtime prerequisites apply |
| `V7-A-004` | **Capability detection e admission**<br>test_hydra_start_admission; test_hydra_benchmark_v4; blocked catalog remains separate | mandatory<br>Admission and runtime prerequisites apply |
| `V7-A-005` | **Circuit breaker e fallback**<br>test_hydra_guard_failures; test_hydra_graph_optional; provider-off real 503 | mandatory<br>Admission and runtime prerequisites apply |
| `V7-B-006` | **Prompt cache nativa**<br>7 cache-enabled native samples; specialized repeated exact prefix; promotion bracket checked | switch<br>Admission and runtime prerequisites apply |
| `V7-B-007` | **Flash Attention Vulkan off/on/auto (campagna finita)**<br>single-variable seven-sample comparison | switch<br>QUARANTINED / Flash Attention requires an explicit finite v18/v19 campaign and its specific ON control; historical GPU profiles remain quarantined. |
| `V7-B-008` | **Batch e ubatch Bonsai**<br>v6 baseline drift guard; no new Bonsai tuning promoted | request_only<br>QUARANTINED / Prism batch/ubatch experiments require quarantined Vulkan path; historical NO_GO retained. |
| `V7-B-009` | **Thread CPU e affinità**<br>2 threads and owned process affinity verified; thread sweep not performed | switch<br>Admission and runtime prerequisites apply |
| `V7-B-010` | **Timing nativi e metriche stadio**<br>native prompt/decode counters; TTFT and pure prefill compute NOT_AVAILABLE | mandatory<br>Admission and runtime prerequisites apply |
| `V7-B-011` | **Contesto, sampler e seed**<br>512 context; raw prompt; greedy seed42 max16 frozen across profiles | switch<br>Admission and runtime prerequisites apply |
| `V7-C-012` | **RAM/VRAM admission e RSS**<br>12GiB RAM admission; 4GiB VRAM reserve; periodic RSS is not hard cap | mandatory<br>Admission and runtime prerequisites apply |
| `V7-C-013` | **Checkpoint prefisso scorer CPU**<br>Request-local native CPU prefix state:checkpoint_tier0=RAM,1=temporary disk file. Disk mode releases retained allocation and restores exact bytes before llama_state_set_data. Exclusive file, checksum, budget and deletion on child exit; no fallback. Not model-weight tiering or cross-request cache. | switch<br>Admission and runtime prerequisites apply |
| `V7-C-014` | **Budget checkpoint scorer CPU**<br>Owns a bounded request-local native CPU full-state checkpoint for exact prefix reuse across alternatives. Cache OFF re-evaluates prefixes. Not GPU KV, cross-request conversation storage or Colibri state. | switch<br>Admission and runtime prerequisites apply |
| `V7-C-015` | **Expert cache slot storage**<br>partial metadata/residency implementation; cache-hit grouped execution not wired; native model pack excluded | request_only<br>BLOCKED / COMPATIBLE_COMPLETE_MOE_TARGET_REQUIRED |
| `V7-C-016` | **Stato nativo Bonsai**<br>Prism v21 session-local native slot save/erase/restore with model/runtime/session identity, SHA256, disk budget, cancellation and cleanup. CPU continuation restored158337104 bytes and reused22 tokens. GPU also requires a finite grant: native state transfer succeeded but repeated-prefix reuse was0; that mode is refused. Not weight tiering. | switch<br>Admission and runtime prerequisites apply |
| `V7-C-017` | **Tiering indice Graphify**<br>Owns repository index data only:0 cold/source disk,1 warm/compressed RAM,2 hot/parsed RAM. Source archive re-read and hashed every request. Not model-weight tiering. | switch<br>Admission and runtime prerequisites apply |
| `V7-C-018` | **Limite commit Windows obbligatorio**<br>Windows process and aggregate Job commit limits:8 GiB for small-model/functional paths,24 GiB for native families. Flags and limits read back before suspended child assignment/resume. Not an RSS or physical-RAM cap; historical peak-accounting discrepancy retained. | mandatory<br>Admission and runtime prerequisites apply |
| `V7-C-019` | **OOM e recupero controllato**<br>budget/cancellation/error tests with fixtures; no deliberate system OOM | mandatory<br>Admission and runtime prerequisites apply |
| `V7-D-020` | **H0 lexical SQLite retrieval**<br>temporary synthetic authorized corpus, hash/scope; real SQLite reads | switch<br>Admission and runtime prerequisites apply |
| `V7-D-021` | **H1 embeddings locali**<br>local CPU encoder and temporary index; provider stopped; historical quality HOLD unchanged | switch<br>Admission and runtime prerequisites apply |
| `V7-D-022` | **H1 v2 coverage/ranking**<br>real CPU retrieval; coverage contracts tested; historical quality HOLD unchanged | switch<br>Admission and runtime prerequisites apply |
| `V7-D-023` | **Context Compiler e RequestGuard**<br>real graph context fed to Qwen; native tokenizer, one selected node; guards remaining zero | switch<br>Admission and runtime prerequisites apply |
| `V7-D-024` | **Bypass query breve**<br>Ciao uses standard path retrieval_cost_not_justified | switch<br>Admission and runtime prerequisites apply |
| `V7-D-025` | **Provenienza hash scope freshness**<br>test_hydra_graph_memory and optional; tamper/expiry/authorization fixtures | mandatory<br>Admission and runtime prerequisites apply |
| `V7-D-026` | **Graphify — contesto dal repository**<br>Selects current local repository sources for Graph retrieval and Context Compiler; validates source identity and freshness. No GPU/weight acceleration. | switch<br>BLOCKED / Missing local repository graph: C:\Users\Stargate\Desktop\BattleTron-LSC-smartConnect\.diagnostics\publish\hydra-one\graphify-out\graph.json |
| `V7-D-027` | **Snapshot e invalidazione indici**<br>HYDRA graph_hybrid and v2 tests; native CPU integration on new corpus | mandatory<br>Admission and runtime prerequisites apply |
| `V7-E-028` | **mmap vs lettura standard**<br>seven native no-mmap samples versus frozen same workload control | switch<br>Admission and runtime prerequisites apply |
| `V7-E-029` | **Loader modello Windows IOCP**<br>Qwen CPU laboratory only: IOCP delivers actual tensor bytes to llama_file::read_raw in the attested isolated CPU runtime. OFF uses the original reference runtime. Requires mmap OFF; no silent fallback or speedup claim. Applies to new requests after owned cleanup. Bonsai PTQ1_0 CPU uses its separate source-pinned Prism IOCP candidate when its v20 manifest exists; missing candidate fails without fallback. GPU Prism remains standard only. loader_mode:0=IOCP,1=standard reads in the same isolated CPU candidate; both require mmap OFF. Candidate instrumentation is not a speedup claim. V22 prefers source-attested rebuilt CPU candidates for Qwen and Bonsai; changed helper identities fail closed. Rebuild and software checks are not model-loading validation. | switch<br>BLOCKED / Isolated IOCP CPU runtime not built/attested; no fallback |
| `V7-E-030` | **Linux O_DIRECT/io_uring**<br>Windows host; Linux-specific branches not hardware tested; io_uring not asserted implemented | request_only<br>UNSUPPORTED / Linux-only O_DIRECT/io_uring; Windows environment. |
| `V7-E-031` | **Prefetch PLE e expert streaming**<br>native large-pack path not admitted; no weight streaming acceleration claimed | request_only<br>BLOCKED / PRISM_GRAPH_BUFFER_REBIND_API_REQUIRED |
| `V7-F-032` | **Speculative draft/target**<br>no admitted compatible draft-target pair and verified backend integration; no second model started | request_only<br>BLOCKED / ATTESTED_DRAFT_TARGET_ADAPTER_REQUIRED |
| `V7-F-033` | **Graph capture e acceleratori secondari**<br>native GPU campaigns remain frozen; no supported graph capture test profile admitted | request_only<br>QUARANTINED / GPU graph capture/secondary accelerators not admitted. |
| `V7-F-034` | **Affinità E-core verificata**<br>Selects up to two allowed group0 E-cores using Windows efficiency classes. Applies and reads back process affinity before child resume. OFF preserves normal adapter affinity; no speedup claimed. | switch<br>Admission and runtime prerequisites apply |
| `V7-G-035` | **Riuso HTTP server testuale CPU**<br>One connection and one in-flight request per native template-aware CPU server. Only fully consumed JSON responses reused; partial/SSE connections discarded. No automatic retry. Connections close at runtime cleanup. | switch<br>Admission and runtime prerequisites apply |
| `V7-G-036` | **Pipeline distribuita e shard staging**<br>no dedicated remote nodes authorized; production Ubuntu untouched | request_only<br>BLOCKED / AUTHORIZED_NODE_EXECUTION_ADAPTER_REQUIRED |
| `V7-G-037` | **Connection loss e timeout trasporto**<br>8 transport tests including controlled errors; no LAN stress | mandatory<br>Admission and runtime prerequisites apply |
| `V7-H-038` | **Text generation app**<br>small Qwen real CPU/Vulkan generation and graph requests | switch<br>Admission and runtime prerequisites apply |
| `V7-H-039` | **Scoring raw continuazioni**<br>real native CPU scorer; blue/red one token, long two tokens; all scored finite sums/means; child exit0; raw only, no System One parity | switch<br>Admission and runtime prerequisites apply |
| `V7-H-040` | **TTS Kokoro**<br>new measured WAV and separate warmup, app registry PASS; old timeout preserved | switch<br>Admission and runtime prerequisites apply |
| `V7-H-041` | **Vision grounding LocateAnything**<br>real synthetic geometry input and valid bounding boxes; semantic quality limited | switch<br>Admission and runtime prerequisites apply |
| `V7-H-042` | **Image Z-Image Turbo**<br>valid generated PNG 256px two steps; pipeline/backend logs preserved | request_only<br>QUARANTINED / Image adapter executes Vulkan diffusion even with CPU weight placement. |
| `V7-H-043` | **Music YuE2**<br>real short generated WAV and symbolic artifact if emitted; native validation | switch<br>Admission and runtime prerequisites apply |
| `V7-H-044` | **Bridge domande isolato CPU**<br>System One-shaped noul/choice/score requests executed by HYDRA native Qwen CPU scoring. Explicit tokenizer/model provenance. No System One contact, Colibri boundary or semantic parity claim; pinned cache unsupported. | switch<br>Admission and runtime prerequisites apply |
| `V7-H-045` | **Scoring CPU con prefisso esatto**<br>Native Qwen C API scoring of exact UTF8 prefix plus ordered continuations. No strip, NFC or implicit template. Actual token boundary checked; incompatible continuations return unscorable_boundary. Original fixture-only contract retained separately. | switch<br>Admission and runtime prerequisites apply |
| `V7-H-046` | **Colibri 35B GS64 model**<br>memory and live tokenizer identity/boundary gates remain BLOCKED; no loading | request_only<br>BLOCKED / FULL35B_RUNTIME_IDENTITY_AND_MEMORY_MANIFEST_REQUIRED |
| `V7-I-047` | **Exclusive lock e reservation**<br>cross-workspace lease, cancellation and admission tests; real serial runs cleanup | mandatory<br>Admission and runtime prerequisites apply |
| `V7-I-048` | **Cancellation e timeout child**<br>controlled child/fixture tests; old failures retained; no global process-name termination | mandatory<br>Admission and runtime prerequisites apply |
| `V7-I-049` | **Publication after cleanup**<br>RED 3 failures then GREEN; native Locate post-fix verification; shared runner/audio fixed too | mandatory<br>Admission and runtime prerequisites apply |
| `V7-I-050` | **Execution identity e immutable events**<br>identity and registry tests; previous rows checked canonical digest | mandatory<br>Admission and runtime prerequisites apply |
| `V7-I-051` | **Routing/planner research variants**<br>baseline, causal, mixed, one research suites; not native generation acceleration | request_only<br>UNSUPPORTED / Routing/planner research variants are software-only; no new runtime dispatcher. |
| `V7-J-052` | **Benchmark persistent history/export**<br>owned app restart verified records; actual SQLite JSON/CSV export | mandatory<br>Admission and runtime prerequisites apply |
| `V7-J-053` | **Monitor live feed**<br>real runner feed producer and software integration; browser visual check unavailable | switch<br>Admission and runtime prerequisites apply |
| `V7-J-054` | **Grafici delle prestazioni**<br>Controls optional charts in the existing page. Safety controls and history remain available. | switch<br>Admission and runtime prerequisites apply |
| `V7-J-055` | **Catalog asset/runtime compatibility**<br>catalog evidence state independent of CANCELLED/metadata failure; 16 identities retained | mandatory<br>Admission and runtime prerequisites apply |
| `V7-J-056` | **Lab OFF isolamento operativo**<br>opt-in contracts; no startup/default/router/System One modifications | mandatory<br>Admission and runtime prerequisites apply |
| `runtime.vulkan` | **Backend VULKAN**<br>ErrorDeviceLost cause UNKNOWN; GPU quarantine | request_only<br>QUARANTINED / ErrorDeviceLost cause UNKNOWN; GPU quarantine |
| `runtime.hip` | **Backend HIP**<br>HIP compiled, GPU inference not admitted | request_only<br>QUARANTINED / HIP compiled, GPU inference not admitted |
| `runtime.cuda` | **Backend CUDA**<br>CUDA toolkit nvcc unavailable; GPU quarantine | request_only<br>QUARANTINED / CUDA toolkit nvcc unavailable; GPU quarantine |

[Parametri, dipendenze e dettagli / Parameters, dependencies and details](docs/FEATURES.md) · [Crediti completi / Full credits](ACKNOWLEDGEMENTS.md)

</details>

<!-- integrated-platform:end -->

## Inizia dai sorgenti

Segui la [guida italiana](docs/INSTALL.it.md) oppure la [English guide](docs/INSTALL.en.md). I pesi dei modelli, gli ambienti Python personali, le credenziali e i runtime compilati della workstation non sono distribuiti. Il bundle HYDRA richiesto dall’integrazione è accompagnato dai suoi sorgenti editabili.

## Beta, con limiti espliciti

Le funzioni sperimentali mantengono controlli di ammissione e dipendenze: GPU, IOCP, tiering, scoring e modelli opzionali richiedono runtime e asset compatibili. Il [registro](docs/FEATURES.md) distingue vincoli attuali e prove storiche. I benchmark upstream non sono misurazioni di Hydra One.

La [verifica di questa copia](docs/VALIDATION.json) copre i test software indicati e la sintassi Python; non certifica prestazioni, tutti i modelli o tutti i percorsi GPU.

## Origine e ringraziamenti

Basato su **[Strata](https://github.com/Niko1221/Strata)** di **Niko1221 e collaboratori**, con modifiche e integrazione di Stargate Labs. L’origine e i copyright restano nei [crediti completi](ACKNOWLEDGEMENTS.md), nella [licenza MIT](LICENSE) e negli [avvisi originali](licenses/).

[App integrate: funzioni, loghi e autori / Integrated apps: functions, logos and authors](docs/APPLICATIONS.it.md)
