<p align="center"><img src="assets/hero.svg" alt="Hydra One — original Hydra One and Stargate Labs branding" width="1280"></p>

# Hydra One

**Hybrid inference. Local models. A controlled laboratory.**

[Italiano](README.md) · [English](README.en.md) · [Installation](docs/INSTALL.en.md) · [Features](docs/FEATURES.md) · [Credits](docs/CREDITS.en.md)

[![Beta](https://img.shields.io/badge/status-beta-16c9e8?style=flat-square)](docs/FEATURES.md) [![License](https://img.shields.io/badge/license-MIT-8faac0?style=flat-square)](LICENSE) [![Stars](https://img.shields.io/github/stars/StargateLabs/Hydra-One?style=flat-square&color=16c9e8)](https://github.com/StargateLabs/Hydra-One/stargazers)

Hydra One is the **Stargate Labs beta**, based on Strata. It brings together our HYDRA One integration, a local-model web workspace and tools to observe, measure and control execution. This publication comes from **our modified local sources**, with native base version 0.1.38, rather than today's upstream main branch.

## Inside Hydra One

| Area | Included implementation | Source |
|---|---|---|
| HYDRA One | Hybrid controller, memory budgets, planning, sidecar and monitoring | [Python engine](hydra-engine/python/) · [integration](serve/hydra_one.py) |
| Native runtime | Owned process lifecycle, admission checks, generation and CPU scoring | [Adapter](serve/hydra_native.py) · [loader](serve/hydra_native_text_server.py) |
| Laboratory | 56 inventoried features, versioned controls, explicit dependencies and gates | [Full register](docs/FEATURES.md) |
| Memory and retrieval | Local graph, H0/H1/H1v2, source provenance and context budgets | [Graph memory](serve/hydra_graph_memory.py) |
| Models and backends | Hugging Face catalogue, GGUF/Safetensors and optional integrations | [Catalogue](serve/catalogue.py) · [backends](serve/optional_backends.py) |
| Workspace | Chat, MCP, monitor, benchmarks and component management | [Interface](serve/web/index.html) · [server](serve/server.py) |


<p align="center"><img src="assets/ecosystem.svg" alt="Hydra One — inference, agents, training, multimodal, knowledge and engineering ecosystem" width="1280"></p>

## Our all-in-one integration

The project brings together inference, chat, agents, MCP, training and multimodal production. The platform guide distinguishes each integration type and links its implementation.

| Area | Components and included work |
|---|---|
| **Inference** | HYDRA One · native C++/CUDA/HIP · llama.cpp · Prism · Transformers/PEFT · Unsloth · AirLLM · Colibri · local APIs |
| **Agents / apps** | OpenCode · DeepSeek Harness · TrueForge · Hermes · Claude Code · native Claude/Antigravity workspace |
| **Tools / memory** | MCP · Playwright browser · shared memory · Headroom · local graph · H0/H1/H1v2 · source provenance |
| **Training** | LoRA · SFT · DPO · GRPO · KTO · reward · VLM · TRL CPU · Soup · Unsloth QLoRA · checkpoints · GGUF export |
| **Multimodal** | Whisper ASR · audio.cpp / Kokoro TTS · VoiceStudio · AudioCraft · source separation · Diffusers image/video · vision projectors |
| **Workspace services** | Open WebUI document/OCR/semantic/reranker workers · model catalogue · downloads/imports · component staging/rollback · telemetry |
| **Research / beta** | 56 baseline experimental features + 3 GPU controls · admission · CPU scheduling · IOCP · scoring · tiering contracts · benchmark history |

**[Platform guide / Guida completa](docs/PLATFORM.en.md)** · [Every source module / Tutti i moduli](docs/MODULES.md) · [Experimental register / Registro sperimentale](docs/FEATURES.md)

These integrations and paths are present in source. See the guide for each component’s prerequisites and gates. Model support depends on architecture, format, runtime and resources; unverified universal compatibility is not claimed.

## The engineering workbench and platform services

### [Performance and Benchmark](docs/WORKBENCH.en.md)

Performance and Benchmark are the workbench for observing models and evaluating the mod’s enhancements. Performance organizes measurements; Benchmark configures and executes tests against the selected backend. Their purpose is to bind a result to its model, runtime, protocol and configuration, rather than publish an unqualified leaderboard. Cache, context, thread and backend changes must be compared through consistent experiments.

### [LLM catalogues and compatibility](docs/CATALOGUES.en.md)

Search results are not automatically executable models. The catalogues connect Hugging Face discovery, publication metadata, variants, files, local inventory and runtime compatibility. Native and optional paths have distinct requirements: an expert pack must not be launched as generic GGUF, and Prism-specific formats must not silently fall back to incompatible runtimes.

### [Updates, backup and recovery](docs/UPDATES.en.md)

The Update Center connects environment inventory, official sources, verified downloads, isolated candidates, validation and component selection. Our adapter is designed to preserve settings, modified sources and data while engines and integrated applications evolve. Available release, downloaded package, validated candidate and active runtime are separate states.

## Start from source

Follow the [English installation guide](docs/INSTALL.en.md) or [Italian guide](docs/INSTALL.it.md). Model weights, personal Python environments, credentials and workstation-specific compiled runtimes are excluded. The HYDRA runtime bundle required by the integration is accompanied by its editable source.

## Explicit beta boundaries

Experimental features retain admission checks and dependency gates: GPU, IOCP, tiering, scoring and optional models require compatible runtimes and assets. The [register](docs/FEATURES.md) separates current gates from historical evidence. Upstream benchmarks are not Hydra One measurements.

The [validation record](docs/VALIDATION.json) covers the listed software tests and Python syntax; it does not qualify throughput, every model or every GPU path.

## Origin and acknowledgements

Based on **[Strata](https://github.com/Niko1221/Strata)** by **Niko1221 and contributors**, with modifications and integration by Stargate Labs. Origin and copyright are preserved in the [full credits](ACKNOWLEDGEMENTS.md), [MIT license](LICENSE) and [original notices](licenses/).

[App integrate: funzioni, loghi e autori / Integrated apps: functions, logos and authors](docs/APPLICATIONS.en.md)
