# Native HYDRA sources / Sorgenti native

The source-only beta contains the main C++ engine under `src/` and `include/hydra/`, a pinned Prism loader overlay under `hydra-engine/native-overlays/`, and `hydra-engine/engine_completion_v22/native_score_recovery.cpp`. It does not ship the developer's EXE/DLL files or attest binaries rebuilt on another PC.

La beta contiene i sorgenti del motore e gli overlay del loader. Non distribuisce i binari personali della workstation. I manifest storici non attestano i nuovi eseguibili.

## Main engine / Motore principale

Use the repository's CMake configuration and the selected CUDA/HIP toolchain. `STRATA_*` options and C++ namespaces remain compatibility identifiers. Public include paths have been changed to `hydra/`; target and executable names retain their native contracts. The original technical build reference is in `docs/reference/AMD_HIP.md`.

## Isolated Prism CPU loader / Loader CPU isolato

1. Download the pinned official source using `python tools/hydra-recovery/fetch_hydra_native.py`. The helper verifies the archive hash before extraction.
2. Copy the four files from `hydra-engine/native-overlays/src/` over the corresponding `src/` files in the downloaded `hydra-engine/engine_completion_v22/prism-source/` tree.
3. In a Visual Studio Developer Command Prompt, configure the downloaded source with CMake. Set `HYDRA_SOURCE_ROOT` to the absolute Hydra One checkout path. Select CPU-only settings: `GGML_CUDA=OFF`, `GGML_VULKAN=OFF`, `GGML_HIP=OFF`, `LLAMA_BUILD_SERVER=ON`.
4. Build the `llama-server` target. Qualify the resulting binaries and dependencies before creating any runtime admission manifest. No loader gate should be bypassed by reusing historical hashes.

Windows IOCP is an experimental, explicit loader path, not a throughput guarantee. Native compilation and model execution are outside the published offline validation record.
