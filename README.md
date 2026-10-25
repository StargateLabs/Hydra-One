<p align="center"><img src="assets/hero.svg" alt="Hydra One — logo originale e laboratorio Stargate Labs" width="1280"></p>

# Hydra One

**Inferenza ibrida. Modelli locali. Un laboratorio sotto controllo.**

[Italiano](README.md) · [English](README.en.md) · [Installazione](docs/INSTALL.it.md) · [Funzionalità](docs/FEATURES.md) · [Crediti](docs/CREDITS.it.md)

[![Beta](https://img.shields.io/badge/status-beta-16c9e8?style=flat-square)](docs/FEATURES.md) [![License](https://img.shields.io/badge/license-MIT-8faac0?style=flat-square)](LICENSE) [![Stars](https://img.shields.io/github/stars/StargateLabs/Hydra-One?style=flat-square&color=16c9e8)](https://github.com/StargateLabs/Hydra-One/stargazers)

Hydra One è la versione beta sviluppata da **Stargate Labs** a partire da Strata. Unisce la nostra integrazione HYDRA One, un workspace web per i modelli locali e strumenti per osservare, misurare e controllare l’esecuzione. Questa pubblicazione deriva dai **nostri sorgenti locali modificati**, con base nativa 0.1.38; non è una copia dell’attuale ramo principale upstream.

## Dentro Hydra One

| Area | Cosa contiene questa versione | Sorgente |
|---|---|---|
| HYDRA One | Controller ibrido, budget di memoria, pianificazione, sidecar e monitoraggio | [Motore Python](hydra-engine/python/) · [integrazione](serve/hydra_one.py) |
| Runtime nativo | Ciclo di vita posseduto, controllo ammissione, generazione e scoring CPU | [Adapter](serve/hydra_native.py) · [loader](serve/hydra_native_text_server.py) |
| Laboratorio | 56 funzioni censite, controlli versionati, dipendenze e blocchi espliciti | [Registro completo](docs/FEATURES.md) |
| Memoria e retrieval | Grafo locale, H0/H1/H1v2, provenienza delle fonti e budget del contesto | [Graph memory](serve/hydra_graph_memory.py) |
| Modelli e backend | Catalogo Hugging Face, GGUF/Safetensors e integrazioni opzionali | [Catalogo](serve/catalogue.py) · [backend](serve/optional_backends.py) |
| Workspace | Chat, MCP, monitor, benchmark e gestione dei componenti | [Interfaccia](serve/web/index.html) · [server](serve/server.py) |

## Inizia dai sorgenti

Segui la [guida italiana](docs/INSTALL.it.md) oppure la [English guide](docs/INSTALL.en.md). I pesi dei modelli, gli ambienti Python personali, le credenziali e i runtime compilati della workstation non sono distribuiti. Il bundle HYDRA richiesto dall’integrazione è accompagnato dai suoi sorgenti editabili.

## Beta, con limiti espliciti

Le funzioni sperimentali mantengono controlli di ammissione e dipendenze: GPU, IOCP, tiering, scoring e modelli opzionali richiedono runtime e asset compatibili. Il [registro](docs/FEATURES.md) distingue vincoli attuali e prove storiche. I benchmark upstream non sono misurazioni di Hydra One.

La [verifica di questa copia](docs/VALIDATION.json) copre i test software indicati e la sintassi Python; non certifica prestazioni, tutti i modelli o tutti i percorsi GPU.

## Origine e ringraziamenti

Basato su **[Strata](https://github.com/Niko1221/Strata)** di **Niko1221 e collaboratori**, con modifiche e integrazione di Stargate Labs. L’origine e i copyright restano nei [crediti completi](ACKNOWLEDGEMENTS.md), nella [licenza MIT](LICENSE) e negli [avvisi originali](licenses/).
