# LLM catalogues, model identity and engine selection

## A compatibility-aware library

Search results are not automatically executable models. The catalogues connect Hugging Face discovery, publication metadata, variants, files, local inventory and runtime compatibility. Native and optional paths have distinct requirements: an expert pack must not be launched as generic GGUF, and Prism-specific formats must not silently fall back to incompatible runtimes.

## Discovery and publication details

The optional catalogue separates chat, code, reasoning and compact categories. Details cover overview, versions/files and author/modifications. Model cards preserve publisher, base-model and license metadata. Extracted sections are bounded and promotional prose is not interpreted as a capability guarantee. Variants in the same publication can be selected without treating each choice as an unrelated search.

## Formats, shards and memory

GGUF headers identify architecture and file roles; weights, projectors and draft files remain distinct. Split files are grouped and checked for completeness. Host-fit checks consider resource and file sizes; missing values do not become zero memory. Safetensors and LoRA use dedicated Python adapters. Catalogue presence does not prove a model fits available RAM or VRAM.

## Local discovery and downloads

Local inventory searches configured roots and known caches, deduplicates paths and binds metadata to actual model files. Download/import paths include byte progress, split handling and publication identity. Model cards and weights retain their own licenses and access conditions. Browsing authors and variants does not implicitly authorize every download.

## Publisher logos and model identities

An original publisher avatar identifies the publisher, not architecture or capabilities of every variant. The brand renderer preserves verified assets. A textual label is preferable to an invented logo when an appropriate official asset is unavailable. Our platform remains branded Hydra One.

## Support follows the actual execution path

Verify format, architecture, quantization, tokenizer/template, runtime version, projector and resources for each model. Multimodal/tool capabilities come from the selected backend. The platform guide lists source-declared architectures and experimental catalogue entries without presenting them as universal model support.

## Implementation / Implementazione

- [serve/catalogue.py](../serve/catalogue.py)
- [serve/catalogue_verified.py](../serve/catalogue_verified.py)
- [serve/optional_catalogue.py](../serve/optional_catalogue.py)
- [serve/local_model_discovery.py](../serve/local_model_discovery.py)
- [serve/model_inventory.py](../serve/model_inventory.py)
- [serve/model_engine_requirements.py](../serve/model_engine_requirements.py)
- [serve/gguf_parts.py](../serve/gguf_parts.py)
- [serve/gguf_runtime_compatibility.py](../serve/gguf_runtime_compatibility.py)
- [serve/studio_model_download.py](../serve/studio_model_download.py)
- [serve/studio_model_import.py](../serve/studio_model_import.py)
- [serve/web/model-brands.js](../serve/web/model-brands.js)

[Platform / Piattaforma](PLATFORM.en.md) · [Source inventory / Inventario](MODULES.md)
