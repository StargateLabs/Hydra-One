"""Launch the original signed Anthropic Windows desktop application.

Inference is configured through Anthropic's documented Windows user policy.
This module never installs software, changes policy, or starts a model.
"""
import os
import json
from pathlib import Path
import subprocess

POLICY = r"SOFTWARE\Policies\Claude"
GATEWAY = "http://127.0.0.1:8090"


def gateway_models(rows):
    """Map only the stable local alias to Desktop's documented gateway tier slot.

    Desktop filters non-Anthropic IDs unless this explicit transport mapping is
    supplied. The display name retains the real local model identity.
    """
    result=[]
    for row in rows:
        row=dict(row)
        if row.get('id')=='strata':
            identity=row.get('alias_of') or 'modello locale selezionato'
            row.update(anthropic_family_tier='sonnet',is_family_default=True,
                       display_name='Strata locale · '+str(identity),
                       description='Gateway locale; tier di trasporto, non un modello Anthropic',
                       supports_1m=False)
        result.append(row)
    return result


def _policy():
    if os.name != "nt":
        return {}
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        values = {}
        try:
            with winreg.OpenKey(hive, POLICY) as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    name, value, kind = winreg.EnumValue(key, i)
                    if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ, winreg.REG_DWORD):
                        values[name] = value
        except FileNotFoundError:
            pass
        if values:
            return values
    library = Path(os.environ.get("LOCALAPPDATA", "")) / "Claude-3p" / "configLibrary"
    try:
        meta = json.loads((library / "_meta.json").read_text(encoding="utf-8-sig"))
        selected = str(meta.get("appliedId", ""))
        import uuid
        uuid.UUID(selected)
        return json.loads((library / (selected + ".json")).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}


def executable():
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "AnthropicClaude"
    # The Squirrel execution stub follows official application updates.
    path = base / "claude.exe"
    return path if os.name == "nt" and path.is_file() else None


def status(root=None):
    path = executable()
    policy = _policy()
    configured = policy.get("inferenceProvider") == "gateway" and policy.get("inferenceGatewayBaseUrl") == GATEWAY
    return {
        "installed": path is not None,
        "official": True,
        "embedded_ui_supported": False,
        "ui_surface": "official_desktop_window",
        "executable": str(path) if path else None,
        "configured": configured,
        "gateway_url": policy.get("inferenceGatewayBaseUrl"),
        "model_discovery": configured and not policy.get("inferenceModels"),
        "inference_verified": False,
        "shared_mcp_configured": any(isinstance(entry, dict) and entry.get("url") == GATEWAY + "/harness/mcp" for entry in policy.get("managedMcpServers", []) or []),
        "shared_mcp_verified": False,
        "message": "Claude Desktop Anthropic originale; connessione effettiva da verificare nell'app." if path else "Claude Desktop ufficiale non installato.",
    }


def launch(root=None):
    path = executable()
    if path is None:
        raise RuntimeError("Claude Desktop ufficiale non installato.")
    # User explicitly requests the official visible UI; do not launch a console helper.
    subprocess.Popen([str(path)], cwd=str(path.parent), close_fds=True)
    return {"ok": True, "launched": True, "desktop": status(root)}
