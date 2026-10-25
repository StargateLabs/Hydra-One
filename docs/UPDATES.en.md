# Updates, mod preservation and recovery

## Integrate upstream changes without losing the mod

The Update Center connects environment inventory, official sources, verified downloads, isolated candidates, validation and component selection. Our adapter is designed to preserve settings, modified sources and data while engines and integrated applications evolve. Available release, downloaded package, validated candidate and active runtime are separate states.

## Inventory and provenance

Component maps bind runtimes and harnesses to their official repositories or distribution channels. Python inventory reads distribution metadata without automatically importing GPU frameworks. Installed versions, selected environments and dependencies remain visible. Release checks are bounded and cached; opening the center must not silently download LLM weights.

## Before a change

The controlled path checks that engines, agents and generators are idle, reclaims idle resources where implemented and verifies memory headroom. The mod backup collects editable sources and configuration, creates recoverable archives and verifies hashes after writing. Generated environments, weights and caches are distinguished from source material.

## Separate candidates and specific checks

Downloads have integrity, size and disk-reserve checks. Extraction stays in candidate directories and rejects unsafe paths. Archive integrity is not runtime compatibility, so preparation, dependency checks and functional validation remain separate. Inference, audio, document and visual Python channels have distinct contracts; selecting one must not silently replace the training environment.

## Selection, rollback and automatic policy

Implemented paths retain selection registries and previous candidates, with identity checks at use time. The automatic queue is persistent and serialized; only components permitted by its existing policy may advance while other channels remain protected. Validation coverage differs by component. Detecting a release does not establish activation or successful execution.

## HYDRA recovery

Recovery validates the manifest, inventory and full capsule hashes before writing. It restores missing files without overwriting modified existing files. The GitHub edition includes a source-only capsule, not personal workstation binaries. Rebuilt native loaders require fresh admission and verified identities.

## Implementation / Implementazione

- [serve/update_center.py](../serve/update_center.py)
- [serve/automatic_updates.py](../serve/automatic_updates.py)
- [serve/safe_update.py](../serve/safe_update.py)
- [serve/dependency_supervisor.py](../serve/dependency_supervisor.py)
- [serve/customization_backup.py](../serve/customization_backup.py)
- [serve/hydra_recovery.py](../serve/hydra_recovery.py)
- [serve/harness_updates.py](../serve/harness_updates.py)
- [serve/python_inference_update.py](../serve/python_inference_update.py)
- [serve/audio_python_update.py](../serve/audio_python_update.py)
- [serve/open_webui_python_update.py](../serve/open_webui_python_update.py)
- [serve/visual_python_update.py](../serve/visual_python_update.py)

[Platform / Piattaforma](PLATFORM.en.md) · [Source inventory / Inventario](MODULES.md)
