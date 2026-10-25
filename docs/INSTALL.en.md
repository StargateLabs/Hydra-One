# Installation — Hydra One beta

This is a source distribution. Use a dedicated directory and keep working installations, models and settings separate.

## Requirements

Python 3.10+. Native builds require CMake 3.24+, a C++ compiler and the GPU toolchain appropriate to your selected backend. On Windows, run native helper builds from a Visual Studio Developer Command Prompt. Model weights and optional runtimes are installed separately.

## Python environment

```powershell
git clone https://github.com/StargateLabs/Hydra-One.git
cd Hydra-One
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m serve.server --help
```

Linux/macOS use `.venv/bin/python`. The inherited native backend targets supported Windows/Linux hardware; creating the Python environment does not install GPU drivers.

## Configure and launch real inference

The operational server is `serve/server.py`. Read `python setup.py --help` and the [base technical setup guide](reference/AI_SETUP.md) before configuring native inference. Setup can download large models and runtime packages; select the backend and model deliberately. Upstream instructions are reference material, not fresh validation of this beta.

A valid native configuration contains `exe`, `args`, `cwd`, `tokenizer` and `model_name`, using your machine's paths. Launch it with:

```powershell
.venv\Scripts\python.exe -m serve.server --engine strata --config path\configuration.json --host 127.0.0.1 --port 8090 --lazy
```

Open `http://127.0.0.1:8090`. Lazy startup does not immediately load a model. The inherited technical driver identifier remains `strata`; our application's displayed identity is Hydra One. Install and verify optional backends through the interface before using them.

## HYDRA laboratory

Start with `python -m serve.hydra_lab_app --help`. The separate lab requires explicit `HYDRA_LAB_MODE=1`, a profile and compatible assets. Blocked controls remain blocked until their dependencies are satisfied. Historical manifests do not attest a newly built executable. Native source overlays are under `hydra-engine/native-overlays`; see [native build notes](NATIVE-BUILD.md).

## Checks and updates

Example offline checks: `python -m unittest serve.test_hydra_one serve.test_hydra_budget serve.test_hydra_request_guard`. The [validation record](VALIDATION.json) identifies the executed scope. Update this repository through Git; do not overwrite Hydra One with an upstream Strata archive.

## Compatibility identifiers

Public headers live under `include/hydra/`. C++ namespaces, CMake flags, `STRATA_*` variables, pack formats, driver names and integration keys remain where they form a technical contract. Blind replacement would break existing configurations or runtimes. Upstream origin and license notices remain in the credits.
