"""One declarative policy per updatable app: how it updates, what proves it, and what is never touched.

This module is deliberately inert: it reads nothing and starts nothing.  The planner,
the automatic queue and the UI use it to decide whether an update may be offered,
which validation is required, and which paths are outside the update boundary.
An unknown identifier fails closed: never automatic, explicit validation, manual
rollback.  A new app must be added here before it can be updated automatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

#: Editable, user-owned trees an app update must never replace or delete.
#: ``mods/`` is our Hydra overlay, ``HYDRA/`` the recovery/protocol assets, and
#: ``data/`` settings, sessions and update journals.
PRESERVED_PATHS = ("mods", "HYDRA", "data")

VALIDATIONS = frozenset({"none", "startup", "cli", "ui", "cpu", "gpu", "gpu_explicit",
                         "environment", "training", "contract", "explicit"})
ROLLBACKS = frozenset({"selection", "pointer", "backup", "manual", "owning_bundle"})


@dataclass(frozen=True)
class Policy:
    id: str
    kind: str
    update_method: str
    automatic: bool
    validation: str
    rollback: str
    reason: str | None = None
    safe_leaf_only: bool = False
    requires: tuple[str, ...] = ()
    description: str = ""
    preserve: tuple[str, ...] = field(default=PRESERVED_PATHS)

    def __post_init__(self):
        if self.validation not in VALIDATIONS:
            raise ValueError(f"{self.id}: unknown validation level {self.validation!r}")
        if self.rollback not in ROLLBACKS:
            raise ValueError(f"{self.id}: unknown rollback method {self.rollback!r}")
        if not self.automatic and not self.reason:
            raise ValueError(f"{self.id}: a protected app must name why it is protected")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "update_method": self.update_method,
            "automatic": self.automatic,
            "validation": self.validation,
            "rollback": self.rollback,
            "reason": self.reason,
            "safe_leaf_only": self.safe_leaf_only,
            "requires": list(self.requires),
            "preserve": list(self.preserve),
            "description": self.description,
        }


def _p(identifier, kind, method, automatic, validation, rollback, **kw) -> Policy:
    return Policy(identifier, kind, method, automatic, validation, rollback, **kw)


POLICIES: dict[str, Policy] = {p.id: p for p in (
    _p("colibri", "engine", "isolated_archive", True, "startup", "selection",
       description="Isolated Colibri runtime; a validated copy is selected, the previous one stays."),
    _p("pytorch", "library", "verified_channel", False, "explicit", "selection",
       reason="build_channel_not_verified",
       description="Custom ROCm build: only a matching, verified build channel may update it."),
    _p("strata", "engine", "isolated_engine", False, "gpu_explicit", "selection",
       reason="engine_requires_operator_validation",
       description="Native engine: startup/libraries can be checked, full GPU inference needs explicit approval."),
    _p("transformers", "library", "managed_environment", False, "environment", "selection",
       reason="managed_by_compatible_environment",
       description="Updated only together with its owning Python environment."),
    _p("airllm", "app", "isolated_environment", True, "startup", "selection",
       description="Isolated AirLLM candidate; the current environment is preserved."),
    _p("voicestudio", "app", "vendor_installer", False, "explicit", "manual",
       reason="desktop_installer_not_integrated",
       description="Vendor desktop installer; no safe in-place integration yet."),
    _p("llama.cpp", "engine", "isolated_archive", True, "gpu", "selection",
       description="Bounded GPU proof; the verified package is selected, previous kept."),
    _p("unsloth", "app", "vendor_installer", False, "explicit", "manual",
       reason="desktop_installer_not_integrated",
       description="Unsloth desktop installer; update only after vendor integration and validation."),
    _p("soup", "app", "isolated_archive", False, "training", "selection",
       reason="release_requires_training_validation",
       description="Soup releases require a training validation before selection."),
    _p("whisper.cpp", "engine", "isolated_archive", True, "cpu", "selection",
       requires=("matching_runtime_variant",),
       description="CPU transcription proof; needs the release variant that matches the installed build."),
    _p("audio.cpp", "engine", "isolated_archive", True, "cpu", "selection",
       description="Bounded CPU TTS proof; the verified copy is selected, previous kept."),
    _p("opencode", "harness", "isolated_harness", True, "ui", "selection",
       description="Isolated npm candidate; session home is backed up and preserved."),
    _p("dsh", "harness", "isolated_harness", True, "ui", "selection",
       description="Isolated npm candidate; session home is backed up and preserved."),
    _p("trueforge", "harness", "isolated_harness", True, "ui", "selection",
       description="Isolated npm candidate; session home is backed up and preserved."),
    _p("browser", "harness", "isolated_harness", True, "ui", "selection",
       requires=("mcp_tool_call",),
       description="MCP candidate must answer a real browser tool call before selection."),
    _p("memory", "harness", "isolated_harness", True, "ui", "selection",
       requires=("mcp_tool_call",),
       description="MCP candidate must answer a real memory tool call before selection."),
    _p("hermes", "harness", "isolated_harness", True, "ui", "selection",
       requires=("node>=26", "mcp_http"),
       description="Hermes 0.23 needs Node >= 26; use a portable Node candidate, never replace the system Node."),
    _p("claude", "harness", "isolated_native", True, "cli", "selection",
       description="Signed native CLI; version and signature are checked before selection."),
    _p("environment:Strata", "environment", "isolated_environment", True, "environment", "selection",
       reason="vendor_environment_requires_explicit_review", safe_leaf_only=True,
       description="Only safe leaf packages update automatically; major libraries need review."),
    _p("environment:Unsloth", "environment", "isolated_environment", True, "environment", "selection",
       reason="vendor_environment_requires_explicit_review", safe_leaf_only=True,
       description="Only safe leaf packages update automatically; major libraries need review."),
    _p("environment:AirLLM", "environment", "isolated_environment", True, "environment", "selection",
       reason="environment_channel_not_verified", safe_leaf_only=True,
       description="Only a verified leaf allowlist may update; the active environment is preserved."),
    _p("environment:Audio generativo", "environment", "isolated_environment", True, "environment", "selection",
       reason="vendor_environment_requires_explicit_review", safe_leaf_only=True,
       description="Only safe leaf packages update automatically; major libraries need review."),
    _p("environment:Open WebUI", "environment", "isolated_environment", True, "environment", "selection",
       reason="vendor_environment_requires_explicit_review", safe_leaf_only=True,
       description="Only safe leaf packages update automatically; major libraries need review."),
    _p("environment:Visuale", "environment", "isolated_environment", True, "environment", "selection",
       reason="vendor_environment_requires_explicit_review", safe_leaf_only=True,
       description="Only safe leaf packages update automatically; major libraries need review."),
    _p("runtime:node", "runtime", "portable_runtime", False, "contract", "pointer",
       reason="runtime_compatibility_not_verified",
       description="Use a side-by-side portable Node; never replace the system Node in place."),
    _p("runtime:uv", "runtime", "portable_runtime", False, "contract", "pointer",
       reason="runtime_compatibility_not_verified",
       description="Use a side-by-side portable uv; never replace the system uv in place."),
    _p("runtime:git", "runtime", "portable_runtime", False, "contract", "pointer",
       reason="runtime_compatibility_not_verified",
       description="Use a side-by-side portable Git; never replace the system Git in place."),
    _p("runtime:npm", "runtime", "owning_engine_bundle", False, "contract", "owning_bundle",
       reason="owning_engine_bundle",
       description="npm follows the Node/engine bundle; it is not replaced on its own."),
)}

#: Generic Python runtimes are vendor environments, not app packages.
_PYTHON_RUNTIME = _p("runtime:python", "runtime", "isolated_environment", False, "environment", "selection",
                     reason="environment_channel_not_verified",
                     description="Python runtimes update with their owning isolated environment.")

UNKNOWN = _p("unknown", "unknown", "manual", False, "explicit", "manual",
             reason="unknown_component_policy",
             description="No policy is registered: the current version is kept.")


def policy_for(identifier: str, kind: str | None = None) -> Policy:
    """The policy for an app/component/runtime, or the fail-closed unknown policy."""
    key = str(identifier or "").strip()
    if key in POLICIES:
        return POLICIES[key]
    if key.startswith("runtime:python:"):
        return _PYTHON_RUNTIME
    base = key.split(":", 1)[1] if ":" in key else key
    for candidate in (base, base.lower()):
        for policy in POLICIES.values():
            if policy.id.lower() == candidate.lower():
                return policy
    if kind:
        for policy in POLICIES.values():
            if policy.kind.lower() == str(kind).lower():
                return policy
    return UNKNOWN


def preserved_paths() -> tuple[str, ...]:
    return PRESERVED_PATHS


def _parts(path: str) -> tuple[str, ...]:
    text = str(path or "").replace("\\", "/").strip()
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"update path is absolute or empty: {path!r}")
    parts = tuple(part for part in PurePosixPath(text).parts if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"update path escapes its root: {path!r}")
    return parts


def assert_preserved(relative_paths) -> None:
    """Raise when an update would write into the Hydra overlay or user data."""
    for path in relative_paths or ():
        parts = _parts(path)
        if parts[0] in PRESERVED_PATHS:
            raise ValueError(f"update would touch a preserved path: {path!r}")


def policy_summary() -> list[dict]:
    return [policy.to_dict() for policy in sorted(POLICIES.values(), key=lambda item: item.id)]
