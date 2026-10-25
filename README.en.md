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

## Start from source

Follow the [English installation guide](docs/INSTALL.en.md) or [Italian guide](docs/INSTALL.it.md). Model weights, personal Python environments, credentials and workstation-specific compiled runtimes are excluded. The HYDRA runtime bundle required by the integration is accompanied by its editable source.

## Explicit beta boundaries

Experimental features retain admission checks and dependency gates: GPU, IOCP, tiering, scoring and optional models require compatible runtimes and assets. The [register](docs/FEATURES.md) separates current gates from historical evidence. Upstream benchmarks are not Hydra One measurements.

The [validation record](docs/VALIDATION.json) covers the listed software tests and Python syntax; it does not qualify throughput, every model or every GPU path.

## Origin and acknowledgements

Based on **[Strata](https://github.com/Niko1221/Strata)** by **Niko1221 and contributors**, with modifications and integration by Stargate Labs. Origin and copyright are preserved in the [full credits](ACKNOWLEDGEMENTS.md), [MIT license](LICENSE) and [original notices](licenses/).
