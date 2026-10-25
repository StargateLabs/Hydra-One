# Hydra One — all-in-one Local AI platform

This guide documents our modified sources without inventing applications or compatibility. Integration takes different forms: inference adapter, owned service, local worker, original transport, laboratory control or optional component. Source presence does not mean all runtimes and weights are installed.

## Engines and execution paths

| Component | Role | Implementation | Source | Boundary |
|---|---|---|---|---|
| **HYDRA One** | Controller ibrido / Hybrid controller | Planning, budgets, sidecar, storage identity, lifecycle and graph integration. | [serve/hydra_one.py](../serve/hydra_one.py) | Backend-owned model residency; not a replacement tensor executor. |
| **Native engine** | C++ / CUDA / HIP | Native model packs, expert execution, cache, speculative paths and CPU/GPU work sharing. | [CMakeLists.txt](../CMakeLists.txt) | Model-pack and toolchain specific; upstream measurements remain attributed. |
| **llama.cpp** | GGUF + local API | Owned server process, split GGUF handling, configuration, model discovery and request transport. | [serve/optional_backends.py](../serve/optional_backends.py) | Architecture, quantization and installed runtime must match. |
| **Prism llama.cpp** | Specialized GGUF | Pinned Prism loader source, model-family checks and isolated native candidate. | [serve/gguf_runtime_compatibility.py](../serve/gguf_runtime_compatibility.py) | Distinct runtime for compatible Prism formats; no silent generic fallback. |
| **Transformers / PEFT** | Safetensors + LoRA | Owned Python text inference, CPU FP32, device-specific GPU paths, local adapters and thread controls. | [serve/safetensors_runtime.py](../serve/safetensors_runtime.py) | Dependencies and model class required; GPU admission is gated separately. |
| **Unsloth** | Inference / QLoRA / Studio | Python backend integration, native Studio service ownership and candidate update handling. | [serve/unsloth_workspace.py](../serve/unsloth_workspace.py) | Installed Unsloth environment required; upstream authentication and frame policy preserved. |
| **AirLLM** | Layer streaming | Project runtime selection and CPU disk-backed layer-streaming integration. | [serve/airllm_runtime.py](../serve/airllm_runtime.py) | Compatible model and runtime needed; disk streaming is not a guaranteed speedup. |
| **Colibri** | Isolated optional engine | Official isolated launcher, controls, local endpoint validation and component updates. | [serve/colibri_workspace.py](../serve/colibri_workspace.py) | Full model assets and matching runtime required; catalogue listing is not successful inference. |
| **Soup** | Training integration | Bundled upstream planning modules, isolated package selection and training runners. | [serve/soup_runtime.py](../serve/soup_runtime.py) | CPU/native/GPU runner restrictions are enforced by training options. |
| **Local API** | OpenAI-compatible transport | Attach compatible local model APIs, normalize messages, tools and response handling. | [serve/optional_inference.py](../serve/optional_inference.py) | Capabilities are reported by the selected model/API; tools and vision are not assumed. |
| **Whisper.cpp** | ASR / translation | Owned local transcription, language controls, decoding parameters, segments and subtitles. | [serve/local_audio.py](../serve/local_audio.py) | Whisper model and selected binary required. |
| **audio.cpp / Kokoro** | Text-to-speech | Local CPU speech and an explicit Kokoro laboratory adapter. | [serve/local_speech.py](../serve/local_speech.py) | Registered speech model/runtime required; separate from a chat-model loader. |
| **Diffusers** | Images / video | Explicit Stable Diffusion, SDXL, inpainting, Stable Video Diffusion and TextToVideoSD worker families. | [serve/local_visual_generation.py](../serve/local_visual_generation.py) | Only implemented pipeline families and installed models; no universal media support. |
| **AudioCraft / audio workers** | Music / effects / voice | Conditioning, native integration, local generation and managed audio workflows. | [serve/local_generative_audio.py](../serve/local_generative_audio.py) | Task-specific assets, conditioning and runtime required. |

## Workspace integration work

### Agents and coding

OpenCode, DeepSeek Harness, TrueForge, Hermes Agent and Claude Code component maps; original transport, sessions and update candidates.

[serve/harness_updates.py](../serve/harness_updates.py) · [serve/original_harness_transport.py](../serve/original_harness_transport.py) · [serve/original_harness_routes.py](../serve/original_harness_routes.py) · [serve/hermes_integration.py](../serve/hermes_integration.py)

### Native workspace

Dashboard, Claude and Antigravity workspace kinds; owned native host and local URL validation.

[serve/native_workspace.py](../serve/native_workspace.py) · [serve/native_window_host.py](../serve/native_window_host.py) · [serve/native_workspace_routes.py](../serve/native_workspace_routes.py)

### MCP and tools

Project MCP configuration, chat tool bridge, shared browser/memory services and controlled candidate activation.

[serve/mcp.py](../serve/mcp.py) · [serve/project_mcp.py](../serve/project_mcp.py) · [serve/shared_agent_services.py](../serve/shared_agent_services.py) · [serve/optional_tools.py](../serve/optional_tools.py)

### Browser and memory services

Playwright MCP and MCP memory server integrated through the shared service configuration.

[serve/trueforge_setup.py](../serve/trueforge_setup.py) · [serve/shared_agent_services.py](../serve/shared_agent_services.py)

### Headroom

Project-scoped runtime metadata, routing enablement and MCP launch contract.

[serve/headroom_integration.py](../serve/headroom_integration.py)

### Open WebUI functions

Document import, local workers for OCR, semantic processing and reranking. Existing module states no separate Open WebUI HTTP server/UI.

[serve/open_webui_runtime.py](../serve/open_webui_runtime.py) · [serve/open_webui_ocr_worker.py](../serve/open_webui_ocr_worker.py) · [serve/open_webui_semantic_worker.py](../serve/open_webui_semantic_worker.py) · [serve/open_webui_reranker_worker.py](../serve/open_webui_reranker_worker.py)

### Model library

HF search, author/model-card metadata, categories, local discovery, split-file identity, imports and byte-level download progress.

[serve/optional_catalogue.py](../serve/optional_catalogue.py) · [serve/local_model_discovery.py](../serve/local_model_discovery.py) · [serve/studio_model_download.py](../serve/studio_model_download.py) · [serve/studio_model_import.py](../serve/studio_model_import.py) · [serve/gguf_parts.py](../serve/gguf_parts.py)

### Fine-tuning

LoRA, explicit SFT/DPO/GRPO/KTO/reward/VLM options; CPU TRL, Soup and Unsloth QLoRA runner policies; checkpoint validation.

[serve/local_training.py](../serve/local_training.py) · [serve/training_options.py](../serve/training_options.py) · [serve/advanced_training_runtime.py](../serve/advanced_training_runtime.py) · [serve/vlm_training_runtime.py](../serve/vlm_training_runtime.py)

### Export and datasets

Owned cancellable GGUF conversion, dataset upload, output validation and checkpoint/resume handling.

[serve/local_export.py](../serve/local_export.py) · [serve/vision_dataset_upload.py](../serve/vision_dataset_upload.py) · [tools/train_local_lora.py](../tools/train_local_lora.py)

### Vision

GGUF projector pairing, CPU default and capability-checked GPU offload; Transformers vision paths and multimodal capability reporting.

[serve/local_vision.py](../serve/local_vision.py) · [serve/transformers_vision.py](../serve/transformers_vision.py) · [serve/multimedia_capabilities.py](../serve/multimedia_capabilities.py)

### Voice production

VoiceStudio jobs/profiles/rendering, local speech, audio library/editing and audiobook planning tests.

[serve/voicestudio.py](../serve/voicestudio.py) · [serve/voicestudio_jobs.py](../serve/voicestudio_jobs.py) · [serve/voicestudio_profiles.py](../serve/voicestudio_profiles.py) · [serve/voicestudio_render.py](../serve/voicestudio_render.py) · [serve/audio_library.py](../serve/audio_library.py) · [serve/audio_edit.py](../serve/audio_edit.py)

### Music and audio

AudioCraft conditioning and training, local generative audio, source separation and task-specific capability checks.

[serve/audiocraft_native.py](../serve/audiocraft_native.py) · [serve/audiocraft_conditioning.py](../serve/audiocraft_conditioning.py) · [serve/audiocraft_training.py](../serve/audiocraft_training.py) · [serve/local_generative_audio.py](../serve/local_generative_audio.py) · [serve/local_separation.py](../serve/local_separation.py)

### Graph and retrieval

Explicit local corpus; SQLite memory, H0/H1/H1v2 graph paths, exact frontend/template reuse, source hashes, freshness and context guards.

[serve/hydra_graph_memory.py](../serve/hydra_graph_memory.py) · [serve/hydra_graph_optional.py](../serve/hydra_graph_optional.py) · [serve/hydra_graphify_runtime.py](../serve/hydra_graphify_runtime.py) · [serve/hydra_graph.py](../serve/hydra_graph.py)

### Laboratory and experiments

56 baseline features plus separate GPU controls; dependency resolution, preview/apply/rollback, execution admission and historical evidence.

[serve/hydra_feature_control.py](../serve/hydra_feature_control.py) · [serve/hydra_lab_app.py](../serve/hydra_lab_app.py) · [serve/hydra_lab_benchmarks.py](../serve/hydra_lab_benchmarks.py) · [serve/hydra_capability_contracts.py](../serve/hydra_capability_contracts.py)

### Native performance research

IOCP source consumer, CPU scheduling, bounded request-local checkpoints, raw scoring, System One bridge contracts and blocked hardware-dependent paths.

[src/platform/direct_file.cpp](../src/platform/direct_file.cpp) · [serve/hydra_cpu_scheduling.py](../serve/hydra_cpu_scheduling.py) · [serve/hydra_scoring_runtime.py](../serve/hydra_scoring_runtime.py) · [serve/hydra_system_one_bridge.py](../serve/hydra_system_one_bridge.py)

### Metrics and verification

Run history, timing, model/runtime identity, live monitoring, source provenance and explicit task-completion contracts.

[serve/instrumentation.py](../serve/instrumentation.py) · [serve/verification_history.py](../serve/verification_history.py) · [serve/hydra_task_completion.py](../serve/hydra_task_completion.py) · [serve/hydra_lab_live.py](../serve/hydra_lab_live.py)

### Process and resource control

Owned children, exclusive GPU leases, cancellation, graceful shutdown, idle unloading and Windows Job limits.

[serve/process_lifecycle.py](../serve/process_lifecycle.py) · [serve/gpu_lease.py](../serve/gpu_lease.py) · [serve/native_graceful_shutdown.py](../serve/native_graceful_shutdown.py) · [serve/winjob.py](../serve/winjob.py)

### Updates and recovery

Official source checks, candidate staging, source fingerprints, explicit activation/rollback, dependency supervision and source-only recovery capsule.

[serve/update_center.py](../serve/update_center.py) · [serve/safe_update.py](../serve/safe_update.py) · [serve/dependency_supervisor.py](../serve/dependency_supervisor.py) · [serve/hydra_recovery.py](../serve/hydra_recovery.py)

### APIs and output

OpenAI/Anthropic-compatible server routes, structured response validation, request monitoring and model lifecycle routes.

[serve/server.py](../serve/server.py) · [serve/structured.py](../serve/structured.py) · [serve/model_engine_routes.py](../serve/model_engine_routes.py)

## Model families and formats

`GGUF` · split GGUF · `Safetensors` · local LoRA adapters · native model packs · multimodal projectors · task-specific media assets.

The GGUF catalogue filter names these architectures:

`gemma`, `gemma2`, `gemma3`, `glm4`, `gpt-oss`, `llama`, `minicpm`, `minicpm3`, `phi2`, `phi3`, `qwen2`, `qwen3`, `qwen35`, `qwen35moe`, `qwen3moe`, `smollm3`, `spark2_5`, `starcoder2`.

This is a source inventory, not qualification of every model in a family. Architecture, quantization, tokenizer, template, projector, runtime version and memory must match. Native packs use their own engine; Prism formats require the appropriate path. Tool calling, image, audio and video support come from actual backend capabilities.

## Registered experimental catalogue

| Model / Asset | Modality | Adapter | Publication state |
|---|---|---|---|
| local/Qwen3-0.6B-Q8_0 | testo / chat | HYDRA ONE HydraClient → llama.cpp CPU/ROCm | Source entry; assets/runtime require local installation and admission |
| mudler/locate-anything.cpp-gguf | visione / grounding | LocateAnything CPU CLI | Source entry; assets/runtime require local installation and admission |
| audio-cpp/audio.cpp-gguf | audio | HYDRA LAB → LocalSpeech → audio.cpp CPU (Kokoro TTS) | Source entry; assets/runtime require local installation and admission |
| Serveurperso/YuE2-GGUF | musica | yue2.cpp CPU CLI, isolated 2-thread build | Source entry; assets/runtime require local installation and admission |
| ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF | testo / MoE | Strata hybrid; budget memoria non attestato | Source entry; assets/runtime require local installation and admission |
| cdiamond/Qwen3.8-27B-iMatrix-NVFP4-MTP-GGUF | testo / MoE | Prism llama.cpp CPU; base generation without MTP | Source entry; assets/runtime require local installation and admission |
| huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF | testo | Prism llama.cpp CPU; no MTP requested | Source entry; assets/runtime require local installation and admission |
| unsloth/MiniMax-H3-GGUF | text/image-to-video | stable-diffusion.cpp video pipeline candidate; NOT_TESTED | Source entry; assets/runtime require local installation and admission |
| unsloth/Qwen3.8-Flash-Next-GGUF | testo / MoE | Strata hybrid; budget memoria non attestato | Source entry; assets/runtime require local installation and admission |
| unsloth/GLM-5.3-Flash-GGUF | testo / MoE | loader architettura da attestare | Source entry; assets/runtime require local installation and admission |
| prism-ml/Ternary-Bonsai-2-27B-gguf | testo / quantizzazione ternaria | Prism llama.cpp CPU CLI | Source entry; assets/runtime require local installation and admission |
| abenzerps/Qwen-Image-2.1-Uncensored-Quantized | immagini | stable-diffusion.cpp Vulkan; CPU text encoder and VAE | Source entry; assets/runtime require local installation and admission |
| unsloth/Qwen-Image-2.1-GGUF | immagini | stable-diffusion.cpp Vulkan; CPU text encoder and VAE | Source entry; assets/runtime require local installation and admission |
| unsloth/Z-Image-Turbo-GGUF | immagini | stable-diffusion.cpp Vulkan / CPU text+VAE | Source entry; assets/runtime require local installation and admission |
| unsloth/Inkling-Small-GGUF | multimodale | adapter multimodale e proiettori da attestare | Source entry; assets/runtime require local installation and admission |
| local/Colibri-Qwen3.6-35B-A3B-i4-gs64 | decisione / testo | Colibri GS64, nessun bridge System One | Source entry; assets/runtime require local installation and admission |

## Experimental controls: complete inventory

[Full feature matrix / Matrice completa](FEATURES.md) · [Source-derived module inventory / Inventario moduli](MODULES.md)

The register includes 56 baseline features and three separate GPU controls. It covers caches and checkpoints, memory tiering, prefetch, speculation, graph capture, direct I/O, distributed transport, retrieval, scoring and multimodal integrations. Each row retains current gates; historical evidence does not automatically promote a feature to operational.

## Verification scope

[VALIDATION.json](VALIDATION.json) · [PUBLICATION-CHECKS.json](PUBLICATION-CHECKS.json) · [Credits / Ringraziamenti](../ACKNOWLEDGEMENTS.md)

Offline checks are not benchmarks and do not qualify every application, model or GPU. Experimental modules and contracts retain their gates rather than becoming unsupported promises.


[Applications, functions, official logos and authors / App, funzioni, loghi ufficiali e autori](APPLICATIONS.en.md)
