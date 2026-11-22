"""The GPU's negotiated PCIe link, from Windows' own PnP device properties.

There is no PCIe throughput or link counter for a GPU on Windows (WMI and PDH have none and AMD's ADL answers
"not supported" on RDNA3), but the PCI bus driver does publish the negotiated link as device properties:
DEVPKEY_PciDevice_CurrentLinkSpeed / CurrentLinkWidth / MaxLinkSpeed / MaxLinkWidth.  `Get-PnpDeviceProperty`
reads them in user mode, so the Monitor can show the real "Gen4 x16" instead of a dash.

The query spawns PowerShell (~ a second), so it runs on a background thread and is cached: readers never block,
and the link is refreshed every REFRESH_S.  That query is not cheap - PowerShell startup plus a PnP
enumeration measured 3.8 s of one core - and the link is effectively static (it never renegotiated in hours of
observation), so the interval is minutes, not seconds: a 1 Hz refresh would cost more than the whole telemetry.
"""
from __future__ import annotations

import re
import subprocess
import threading
import time

REFRESH_S = 900.0

# "Gen" names for the PnP enum (1 = 2.5 GT/s, 2 = 5, 3 = 8, 4 = 16, 5 = 32, 6 = 64)
_PS = (
    "Get-PnpDevice -Class Display -Status OK | ForEach-Object {"
    " $i=$_.InstanceId;"
    " $s=(Get-PnpDeviceProperty -InstanceId $i -KeyName DEVPKEY_PciDevice_CurrentLinkSpeed -ErrorAction SilentlyContinue).Data;"
    " $w=(Get-PnpDeviceProperty -InstanceId $i -KeyName DEVPKEY_PciDevice_CurrentLinkWidth -ErrorAction SilentlyContinue).Data;"
    " $ms=(Get-PnpDeviceProperty -InstanceId $i -KeyName DEVPKEY_PciDevice_MaxLinkSpeed -ErrorAction SilentlyContinue).Data;"
    " $mw=(Get-PnpDeviceProperty -InstanceId $i -KeyName DEVPKEY_PciDevice_MaxLinkWidth -ErrorAction SilentlyContinue).Data;"
    " if ($s) { \"$i|$s|$w|$ms|$mw\" } }"
)

_cache: dict | None = None
_started = False
_lock = threading.Lock()


def _query() -> dict | None:
    """One PowerShell round: the AMD display device's link, or the first one that reports it."""
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _PS],
                             capture_output=True, text=True, timeout=25,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    best = None
    for line in out.stdout.splitlines():
        parts = [p.strip() for p in line.strip().split("|")]
        if len(parts) != 5:
            continue
        ident, speed, width, mspeed, mwidth = parts
        try:
            link = {"gen": int(speed), "width": int(width),
                    "gen_max": int(mspeed) if mspeed else int(speed),
                    "width_max": int(mwidth) if mwidth else int(width),
                    "device": ident}
        except ValueError:
            continue
        if "VEN_1002" in ident.upper():          # AMD: this is the card Strata runs on
            return link
        best = best or link
    return best


def _loop() -> None:
    global _cache
    while True:
        link = _query()
        if link:
            with _lock:
                _cache = link
        time.sleep(REFRESH_S)


def start() -> None:
    """Start the background refresher once (idempotent)."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="pcie-link").start()


def current() -> dict | None:
    """The cached link ({gen, width, gen_max, width_max}), or None until the first query lands."""
    with _lock:
        return dict(_cache) if _cache else None
