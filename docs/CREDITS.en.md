# Acknowledgements and provenance — Hydra One

Hydra One is a **beta fork of Strata**, created by **Niko1221 and the Strata contributors**. Stargate Labs maintains the modifications and HYDRA One integration; upstream work remains credited to its original authors. We thank the authors, maintainers and contributors whose work makes this project possible.

## Included code and assets

| Progetto / Project | Autori / Authors | Contributo / Contribution | Licenza / License |
|---|---|---|---|
| [Strata](https://github.com/Niko1221/Strata) | Niko1221 e collaboratori / contributors | Base del fork; motore nativo, server e interfaccia / Fork foundation: native engine, server and interface | MIT; licenses/Strata-MIT.txt |
| [llama.cpp / ggml](https://github.com/ggml-org/llama.cpp) | ggml authors e collaboratori / contributors | Backend, formati GGUF, quantizzazione, mtmd e strumenti / Backends, GGUF, quantization, mtmd and tools | MIT; licenses/ggml-MIT.txt; licenses/llama.cpp-MIT.txt |
| [Prism llama.cpp](https://github.com/PrismML-Eng/llama.cpp) | PrismML-Eng e autori upstream / upstream authors | Sorgente del loader HYDRA nativo / HYDRA native-loader source; commit e3de715222b2667c54a267441159a5729f11155e | MIT; licenses/Prism-llama.cpp-MIT.txt |
| [Soup](https://github.com/MakazhanAlpamys/Soup) | Makazhan Alpamys / Soup Team | Moduli di pianificazione inclusi / Bundled planning modules; commit 61e8c2bf354393cea85002401d0bde803b48f614 | Apache-2.0; licenses/Soup-* |
| [xterm.js](https://github.com/xtermjs/xterm.js) | xterm.js authors; SourceLair; Christopher Jeffrey | Terminale web / Web terminal | MIT; licenses/xterm-MIT.txt |
| [Lucide / Feather](https://github.com/lucide-icons/lucide) | Lucide Icons and Contributors; Cole Bemis | Icone UI e icone derivate da Feather / UI icons and Feather-derived icons | ISC / MIT; licenses/Lucide-Feather-LICENSE.txt |
| [Outfit](https://github.com/Outfitio/Outfit-Fonts) | The Outfit Project Authors | Caratteri dell’interfaccia / Interface font | SIL OFL 1.1; licenses/Outfit-OFL-1.1.txt |
| [Sora](https://github.com/sora-xor/sora-font) | The Sora Project Authors | Caratteri dell’interfaccia / Interface font | SIL OFL 1.1; licenses/Sora-OFL-1.1.txt |

The main CMake llama.cpp reference is `3cf03257f219afbe7334045ff7c6a06ac68c627d`; the Prism loader uses the separate commit above. Original licenses and copyright notices are preserved in [licenses](../licenses/). [LICENSE-MANIFEST.json](LICENSE-MANIFEST.json) records their provenance and SHA-256 hashes.

## Optional integrations and tools

We acknowledge **Unsloth, Transformers, PyTorch, AirLLM, Colibri, Whisper.cpp, audio.cpp, AudioCraft, VoiceStudio, OpenCode, DeepSeek Harness, TrueForge, Hermes Agent, Claude Code, Playwright and Model Context Protocol**. Official references come from source code and component maps. A catalogue entry does not establish successful execution, universal compatibility or redistribution of that project's source. Each component retains its own license and terms.


| Componente / Component | Sorgente ufficiale / Official source |
|---|---|
| airllm | [lyogavin/airllm](https://github.com/lyogavin/airllm) |
| audio.cpp | [unslothai/audio.cpp](https://github.com/unslothai/audio.cpp) |
| browser | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) |
| claude | [anthropics/claude-code](https://github.com/anthropics/claude-code) |
| colibri | [JustVugg/colibri](https://github.com/JustVugg/colibri) |
| dsh | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) |
| hermes | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) |
| llama.cpp | [unslothai/llama.cpp](https://github.com/unslothai/llama.cpp) |
| memory | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) |
| opencode | [anomalyco/opencode](https://github.com/anomalyco/opencode) |
| pytorch | [pytorch/pytorch](https://github.com/pytorch/pytorch) |
| soup | [MakazhanAlpamys/Soup](https://github.com/MakazhanAlpamys/Soup) |
| strata | [Niko1221/Strata](https://github.com/Niko1221/Strata) |
| transformers | [huggingface/transformers](https://github.com/huggingface/transformers) |
| trueforge | [truefoundry/trueforge](https://github.com/truefoundry/trueforge) |
| unsloth | [unslothai/unsloth](https://github.com/unslothai/unsloth) |
| voicestudio | [debpalash/VoiceStudio](https://github.com/debpalash/VoiceStudio) |
| whisper.cpp | [unslothai/whisper.cpp](https://github.com/unslothai/whisper.cpp) |

## Models and research

We retain upstream acknowledgements to the **Qwen team**, **ISTA-DASLab**, **UkisAI**, **Unsloth** and [eddoursul/Strata](https://github.com/eddoursul/Strata), and ideas credited to [Splash](https://github.com/incoai/splash), [ninfer](https://github.com/Neroued/ninfer) and [HyperQwen](https://github.com/syv-ai/HyperQwen). Named Strata contributions include [@pjgmobile](https://github.com/pjgmobile) (Coder, PR #54), [@code-martin](https://github.com/code-martin) (monitor concept, PR #22) and [@bsorensen110](https://github.com/bsorensen110) (AMD optimizations, PR #329 and #337). These credits do not turn upstream benchmarks into Hydra measurements.

Other model publishers referenced by the catalogue are recorded in the source inventory. Model weights retain their own model cards, licenses, restrictions and access conditions; the fork's license does not supersede them. The same applies to datasets and vectors derived from model activations.

## Dependencies, logos and inventory

Pinned direct and transitive Python dependencies are listed in [PYTHON-DEPENDENCIES.txt](PYTHON-DEPENDENCIES.txt). Python, NumPy, Jinja2 and other packages retain their respective authors and licenses. This inventory does not replace the license notices shipped with each package.

**Stargate Labs** and **Hydra One** logos are the project's original assets. Third-party logos identify their respective projects, imply no affiliation or endorsement, and are not automatically relicensed under MIT. Original asset-source maps remain with the interface.

[SOURCE-REFERENCES.json](SOURCE-REFERENCES.json) records GitHub and Hugging Face references found in source and documentation, with origin files and line numbers. It also includes research and test references: a citation does not establish bundled code or runtime support. Update this verifiable inventory when components change.

[Ringraziamenti in italiano](CREDITS.it.md)
