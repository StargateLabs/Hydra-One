<p align="center"><img src="assets/hero.svg" alt="Hydra One — logo originale e laboratorio Stargate Labs" width="1280"></p>

# Hydra One

**Inferenza ibrida. Modelli locali. Un laboratorio sotto controllo.**

[Italiano](README.md) · [English](README.en.md) · [Installazione](docs/INSTALL.it.md) · [Funzionalità](docs/FEATURES.md) · [Crediti](docs/CREDITS.it.md)

[![Beta](https://img.shields.io/badge/status-beta-16c9e8?style=flat-square)](docs/FEATURES.md) [![License](https://img.shields.io/badge/license-MIT-8faac0?style=flat-square)](LICENSE) [![Stars](https://img.shields.io/github/stars/StargateLabs/Hydra-One?style=flat-square&color=16c9e8)](https://github.com/StargateLabs/Hydra-One/stargazers)

Hydra One è la versione beta sviluppata da **Stargate Labs** a partire da Strata. Unisce la nostra integrazione HYDRA One, un workspace web per i modelli locali e strumenti per osservare, misurare e controllare l’esecuzione. Questa pubblicazione deriva dai **nostri sorgenti locali modificati**, con base nativa 0.1.38; non è una copia dell’attuale ramo principale upstream.

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

## Inizia dai sorgenti

Segui la [guida italiana](docs/INSTALL.it.md) oppure la [English guide](docs/INSTALL.en.md). I pesi dei modelli, gli ambienti Python personali, le credenziali e i runtime compilati della workstation non sono distribuiti. Il bundle HYDRA richiesto dall’integrazione è accompagnato dai suoi sorgenti editabili.

## Beta, con limiti espliciti

Le funzioni sperimentali mantengono controlli di ammissione e dipendenze: GPU, IOCP, tiering, scoring e modelli opzionali richiedono runtime e asset compatibili. Il [registro](docs/FEATURES.md) distingue vincoli attuali e prove storiche. I benchmark upstream non sono misurazioni di Hydra One.

La [verifica di questa copia](docs/VALIDATION.json) copre i test software indicati e la sintassi Python; non certifica prestazioni, tutti i modelli o tutti i percorsi GPU.

## Origine e ringraziamenti

Basato su **[Strata](https://github.com/Niko1221/Strata)** di **Niko1221 e collaboratori**, con modifiche e integrazione di Stargate Labs. L’origine e i copyright restano nei [crediti completi](ACKNOWLEDGEMENTS.md), nella [licenza MIT](LICENSE) e negli [avvisi originali](licenses/).

[App integrate: funzioni, loghi e autori / Integrated apps: functions, logos and authors](docs/APPLICATIONS.it.md)
