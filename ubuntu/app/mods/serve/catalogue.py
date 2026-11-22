"""serve/catalogue.py - a small catalogue of models this engine can actually run.

The engine reads ONE architecture: `qwen4exp` (Qwen3.8-Flash-Next and its derivatives - the GSQ-RCO
quants by ISTA-DASLab, the Coder release, UkisAI's Swift 1.5, and Unsloth's dynamic re-quants).  There
is no code in `src/` for any other architecture, so a catalogue entry is only useful when its first
GGUF shard says `general.architecture = qwen4exp`.

Workflow, and the order matters because the downloads are 58-330 GB:
  1. `candidates()`  - the repositories worth looking at (the official ones from setup.py, plus
                       whatever HuggingFace's search returns for the model family).
  2. `inspect(repo)` - reads ONLY the first shard's GGUF header over HTTP (a Range request, a few MB
                       at most) and reports the architecture, the expert count, the layer count and
                       the quant of that directory.  A wrong architecture is caught here, in seconds,
                       instead of after a 100 GB download.
  3. `download(...)` - huggingface_hub (already a dependency) into Strata-data/models/<dir>.
  4. `pack(...)`     - tools/iq_pack.py builds the native pack the engine loads.
  5. `register(...)` - writes strata-<key>.json next to the others, so the dashboard's model menu
                       shows it as "sul disco" and the switch button can load it.

Nothing here changes the engine or an existing configuration: it only adds files under Strata-data,
writes new strata-<key>.json files, and reports.  A pack or a config that already exists is never
overwritten.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import struct
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "Strata-data"

# The repositories the project itself ships configurations for (setup.py's FAMILIES), plus the
# per-family directories that hold the actual quantisations.
OFFICIAL = [
    {"repo": "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF", "family": "qwen",
     "title": "Qwen3.8-Flash-Next (GSQ-RCO)", "by": "ISTA-DASLab",
     "dirs": ["Q2_0", "IQ2_XS", "IQ3_XXS", "IQ3_S"], "mmproj": "mmproj-Qwen3.8-Flash-Next-BF16.gguf"},
    {"repo": "ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF", "family": "coder",
     "title": "Qwen3.8-Flash-Next Coder (GSQ-RCO)", "by": "ISTA-DASLab",
     "dirs": ["IQ1_M"], "mmproj": "mmproj-Qwen3.8-Flash-Next-BF16.gguf"},
    {"repo": "ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF", "family": "swift",
     "title": "Swift 1.5 (finetune)", "by": "UkisAI",
     "dirs": ["Q2_0", "IQ2_XS", "IQ3_XXS"], "mmproj": "mmproj-Swift-Qwen3.8-Flash-Next-BF16.gguf"},
    {"repo": "unsloth/Qwen3.8-Flash-Next-GGUF", "family": "unsloth",
     "title": "Qwen3.8-Flash-Next (Unsloth Dynamic)", "by": "Unsloth",
     "dirs": ["UD-IQ1_S", "UD-IQ1_M", "UD-Q2_K_XL", "UD-IQ3_XXS", "UD-Q3_K_XL", "UD-IQ4_XS",
              "UD-Q4_K_XL", "UD-Q5_K_XL", "UD-Q6_K_XL", "Q8_0"],
     "mmproj": None, "mtp": "MTP"},
]

# The GGUF metadata value types (gguf spec v3, the wire format the reader walks).
_T_U8, _T_I8, _T_U16, _T_I16, _T_U32, _T_I32 = 0, 1, 2, 3, 4, 5
_T_F32, _T_BOOL, _T_STRING, _T_ARRAY, _T_U64, _T_I64, _T_F64 = 6, 7, 8, 9, 10, 11, 12
_FIXED = {_T_U8: 1, _T_I8: 1, _T_U16: 2, _T_I16: 2, _T_U32: 4, _T_I32: 4, _T_F32: 4, _T_BOOL: 1,
          _T_U64: 8, _T_I64: 8, _T_F64: 8}
_T_FMT = {_T_U8: "<B", _T_I8: "<b", _T_U16: "<H", _T_I16: "<h", _T_U32: "<I", _T_I32: "<i",
          _T_F32: "<f", _T_BOOL: "<B", _T_U64: "<Q", _T_I64: "<q", _T_F64: "<d"}


def _range_bytes(url: str, nbytes: int, timeout: float = 45.0) -> bytes:
    """The first `nbytes` of a remote file, one HTTP Range request.  Falls back to a plain GET."""
    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{nbytes - 1}",
                                               "User-Agent": "strata-catalogue/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(nbytes)
    except urllib.error.HTTPError as e:
        if e.code != 416:            # 416: the file is smaller than the range
            raise
    req = urllib.request.Request(url, headers={"User-Agent": "strata-catalogue/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(nbytes)


def read_gguf_header(url: str, nbytes: int = 4 << 20) -> dict:
    """Parse the KV metadata at the start of a remote GGUF.  Returns the keys we care about.

    The header is: magic 'GGUF', version (u32), tensor_count (u64), kv_count (u64), then the KV
    pairs.  Values can be big (token arrays, templates), so the walk skips unknown keys by their
    declared size and stops as soon as `general.architecture` has been seen.
    """
    buf = _range_bytes(url, nbytes)
    if len(buf) < 24 or buf[:4] != b"GGUF":
        raise ValueError("not a GGUF file (bad magic)")
    version, = struct.unpack_from("<I", buf, 4)
    n_tensors, = struct.unpack_from("<Q", buf, 8)
    n_kv, = struct.unpack_from("<Q", buf, 16)
    at = 24

    def require(size):
        if size < 0 or at < 0 or at + size > len(buf):
            raise ValueError('GGUF metadata exceeds the inspected header range')

    def string() -> str:
        nonlocal at
        require(8)
        n, = struct.unpack_from("<Q", buf, at); at += 8
        require(n)
        s = buf[at:at + n].decode("utf-8", "replace"); at += n
        return s

    def value(t: int):
        nonlocal at
        if t == _T_STRING:
            return string()
        if t == _T_ARRAY:
            require(12)
            sub, = struct.unpack_from("<I", buf, at); at += 4
            cnt, = struct.unpack_from("<Q", buf, at); at += 8
            if sub == _T_STRING:
                require(cnt * 8)
                out = []
                for _ in range(min(cnt, 8)):       # enough to see what it is, not all of it
                    out.append(string())
                for _ in range(cnt - min(cnt, 8)):  # walk the rest by size
                    require(8)
                    n, = struct.unpack_from("<Q", buf, at); at += 8
                    require(n); at += n
                return out if cnt <= 8 else out + [f"... {cnt} total"]
            step = _FIXED.get(sub)
            if step is None:
                raise ValueError(f"array of unsupported type {sub}")
            require(step * cnt)
            if cnt<=512 and sub in _T_FMT:
                out=[struct.unpack_from(_T_FMT[sub],buf,at+i*step)[0] for i in range(cnt)]
                at+=step*cnt
                return out
            at += step * cnt
            return f"[{cnt} x {sub}]"
        fmt = _T_FMT.get(t)
        if fmt is None:
            raise ValueError(f"unsupported value type {t}")
        require(_FIXED[t])
        v, = struct.unpack_from(fmt, buf, at); at += _FIXED[t]
        return v

    meta: dict = {}
    complete = True
    for _ in range(n_kv):
        try:
            key = string()
            require(4)
            t, = struct.unpack_from("<I", buf, at); at += 4
            meta[key] = value(t)
        except (ValueError, struct.error):
            complete = False
            break
        if key == "general.architecture" and "tokenizer.ggml.tokens" in meta:
            continue
    return {"version": version, "tensors": n_tensors, "kv": n_kv, "meta": meta, "metadata_complete": complete}


def _shard_url(repo: str, path: str) -> str:
    return f"https://huggingface.co/{repo}/resolve/main/{path}"


def _repo_tree(repo: str, timeout: float = 40.0) -> list:
    url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def _quant_of(name: str) -> str | None:
    """The quantisation token of a GGUF file name (Q2_0, IQ3_XXS, UD-Q4_K_XL, ...).

    Some repositories keep the GGUFs in per-quant directories (ISTA-DASLab); others put every quant
    at the root and name it in the file (UkisAI's Swift).  Grouping by this token covers both."""
    base = name.rsplit("/", 1)[-1]
    m = re.search(r"-((?:UD-)?(?:IQ|Q)\d[\w.]*?)-0000\d-of-\d{5}\.gguf$", base)
    if m:
        return m.group(1)
    m = re.search(r"((?:UD-)?(?:IQ|Q)\d[\w.]*?)(?:-0000\d-of-\d{5})?\.gguf$", base)
    return m.group(1) if m else None


def groups(files: list) -> dict:
    """{label: [file, ...]} for every quantisation in a repository.

    The label is the directory name when the files live in one, otherwise the quant token from the
    file name, so `inspect()` can be asked for either."""
    out: dict = {}
    for f in files:
        if f.get("type") != "file" or not f["path"].endswith(".gguf"):
            continue
        path = f["path"]
        if "/" in path:
            label = path.split("/")[0]
        else:
            label = _quant_of(path)
            if label is None:                 # the vision projector and the MTP heads
                continue
        out.setdefault(label, []).append(f)
    return out


def _first_shard(files: list, direc: str) -> dict | None:
    """The '-00001-of-0000N' shard of one quantisation, or its single file if it is not split."""
    mine = list(files)
    if not mine:
        return None
    one = [f for f in mine if re.search(r"-00001-of-\d{5}\.gguf$", f["path"])]
    return (one or mine)[0]


def inspect(repo: str, direc: str | None = None, timeout: float = 40.0) -> dict:
    """Read one directory's first shard header over HTTP.  Nothing is downloaded to disk."""
    files = _repo_tree(repo, timeout)
    grp = groups(files)
    dirs = sorted(grp)
    if direc is None:
        direc = dirs[0] if dirs else None
    if direc is None:
        return {"repo": repo, "error": "no GGUF quantisation found in this repository"}
    if direc not in grp:
        return {"repo": repo, "dir": direc, "dirs_available": dirs,
                "error": f"no such quantisation here: {direc}"}
    mine = grp[direc]
    shard = _first_shard(mine, direc)
    if shard is None:
        return {"repo": repo, "dir": direc, "error": "no shard found"}
    total = sum(f.get("size") or 0 for f in mine)
    out = {"repo": repo, "dir": direc, "shard": shard["path"],
           "download_gib": round(total / 2 ** 30, 1),
           "shards": len(mine)}
    try:
        h = read_gguf_header(_shard_url(repo, shard["path"]))
    except Exception as e:                       # a network or format problem is a result, not a crash
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    m = h["meta"]
    out["architecture"] = m.get("general.architecture")
    out["name"] = m.get("general.name")
    out["layers"] = m.get("qwen4exp.block_count") or m.get("qwen4exp.layer_count")
    out["experts"] = m.get("qwen4exp.expert_count")
    out["file_type"] = m.get("general.file_type")
    out["compatible"] = out["architecture"] == "qwen4exp"
    out["dirs_available"] = dirs
    out["fit"] = fit(key=direc, download_gib=out.get("download_gib"), architecture=out.get("architecture"))
    return out


def search(query: str = "Qwen3.8-Flash-Next", limit: int = 60, timeout: float = 40.0) -> list:
    """HuggingFace's model search, narrowed to what could plausibly be this family."""
    url = ("https://huggingface.co/api/models?search=" + urllib.parse.quote(query)
           + f"&limit={limit}&sort=downloads&direction=-1")
    with urllib.request.urlopen(url, timeout=timeout) as r:
        found = json.load(r)
    out = []
    for x in found:
        rid = x.get("id") or ""
        if not rid:
            continue
        out.append({"repo": rid, "downloads": x.get("downloads") or 0,
                    "likes": x.get("likes") or 0,
                    "tags": [t for t in (x.get("tags") or [])
                             if t.startswith("base_model") or t in ("gguf", "unsloth")][:4]})
    return out


def known(model_key: str) -> dict | None:
    """The official entry (family, directories) for one of the model keys setup.py knows."""
    for e in OFFICIAL:
        for d in e["dirs"]:
            if d.lower().replace("-", "_") == model_key.lower().replace("-", "_"):
                return {**e, "dir": d}
    return None


import urllib.parse  # noqa: E402  (used by search(); kept next to its reader for readability)


def repo_files(repo: str, quant: str, mtp: bool = False, timeout: float = 40.0) -> list:
    """The relative paths to download for one quantisation: its shards plus the vision projector.

    huggingface_hub takes this list as `allow_patterns`, so the download is exactly the files the
    engine needs - not the BF16 shards, the Q8_0 ones or the other nine quantisations beside them."""
    files = _repo_tree(repo, timeout)
    grp = groups(files)
    mine = grp.get(quant)
    if mine is None:
        return []
    out = [f["path"] for f in mine]
    for f in files:
        if f.get("type") == "file" and f["path"].lower().endswith(".gguf") \
                and "mmproj" in f["path"].lower():
            out.append(f["path"])
            break
    if mtp:                                   # the draft head: ~23 GiB, only when asked for
        out.extend(mtp_files(repo, timeout))
    return sorted(set(out))


def free_gib(path) -> float:
    """Free space on the volume that holds `path` (its nearest existing parent)."""
    p = pathlib.Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return round(shutil.disk_usage(str(p)).free / 2 ** 30, 1)


def space_needed(download_gib: float) -> float:
    """Download plus the pack it produces.

    A pack keeps the small projection tensors (`dense.bin`) and the index; the experts are read from
    the GGUF itself unless `--experts-bin` is used, and with `--base` the shared floats are reused.  An
    empirical margin of 4 GiB covers the dense tensors and the slowness of a nearly full volume (a real pack here measured 1.4 GiB: dense.bin only)."""
    return round(download_gib * 1.02 + 4.0, 1)


def check_space(download_gib: float, dest_root) -> dict:
    free = free_gib(dest_root)
    need = space_needed(download_gib)
    return {"free_gib": free, "needed_gib": need, "ok": free >= need}


def mtp_files(repo: str, timeout: float = 40.0) -> list:
    """The MTP (draft) heads a repository publishes, if any - the speculative path needs one."""
    files = _repo_tree(repo, timeout)
    return sorted(f["path"] for f in files
                  if f.get("type") == "file" and f["path"].lower().endswith(".gguf")
                  and f["path"].split("/")[0].lower() == "mtp")


# ------------------------------------------------------------------------------------------------
# Can this machine RUN it?  Two questions that have nothing to do with the download: the RAM the
# engine maps (its "arena") and the VRAM the expert cache uses.  The per-model figures are the ones
# the project itself publishes in setup.py's MODELS registry (ram_gb = the PC the size wants,
# arena_gb = what the engine maps); a model outside that list is estimated from its file size and
# MARKED as an estimate, never presented as fact.
# ------------------------------------------------------------------------------------------------
HOST_TABLE = {          # source: setup.py -> MODELS (download_gb, ram_gb, arena_gb)
    "Q2_0":       {"download_gb": 66.4, "ram_gb": 48, "arena_gb": 34.0},
    "IQ2_XS":     {"download_gb": 68.0, "ram_gb": 48, "arena_gb": 35.5},
    "IQ3_XXS":    {"download_gb": 75.8, "ram_gb": 60, "arena_gb": 42.9},
    "IQ3_S":      {"download_gb": 83.6, "ram_gb": 62, "arena_gb": 50.3},
    "IQ1_M":      {"download_gb": 58.4, "ram_gb": 32, "arena_gb": 23.4},
    "UD-Q4_K_XL": {"download_gb": 111.3, "ram_gb": 48, "arena_gb": 77.0},
}


def _vram_total_gib() -> float | None:
    """The card's own VRAM size: the display driver's registry HardwareInformation.qwMemorySize.

    The same reading `serve/telemetry.py` makes (AdapterRAM is a signed int and reports -1 MiB on a
    24 GB card, so the registry value is the one to use)."""
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Control\Class"
                             r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
        i = 0
        while True:
            try:
                sub = winreg.OpenKey(key, f"{i:04d}")
            except OSError:
                break
            try:
                desc = winreg.QueryValueEx(sub, "DriverDesc")[0] or ""
                if "AMD" in desc or "Radeon" in desc:
                    return round(int(winreg.QueryValueEx(sub, "HardwareInformation.qwMemorySize")[0]) / 2 ** 30, 1)
            except OSError:
                pass
            finally:
                winreg.CloseKey(sub)
            i += 1
    except Exception:
        pass
    return None


def host() -> dict:
    """What this machine has, right now."""
    out = {"ram_total_gib": None, "ram_free_gib": None, "vram_total_gib": _vram_total_gib(),
           "models_dir": str(DATA / "models"), "free_gib": free_gib(DATA / "models")}
    try:
        import psutil
        vm = psutil.virtual_memory()
        out["ram_total_gib"] = round(vm.total / 2 ** 30, 1)
        out["ram_free_gib"] = round(vm.available / 2 ** 30, 1)
    except Exception:
        pass                                    # the caller reports what it has, not what it lacks
    return out


def fit(key: str = None, download_gib: float = None, architecture: str = None,
        on_disk: bool = False) -> dict:
    """The verdict for one model on THIS machine.

    Levels, because "runs" has two different meanings here:
      'piena' - the arena fits in RAM: the engine keeps the experts in memory and the GPU cache.
      'disco' - it does NOT fit in RAM, so the engine reads most experts from the SSD (the project's
                UD-Q4_K_XL path: it runs, at 7-8.5 tok/s, not at 45).
      'no'    - wrong architecture, or the download does not fit on the disk at all.
    """
    h = host()
    reasons, estimated = [], False
    if architecture is not None and architecture != "qwen4exp":
        return {"level": "no", "why": f"architettura {architecture}: il motore legge solo qwen4exp",
                "host": h, "estimated": False}
    entry = None
    if key:
        for k, v in HOST_TABLE.items():
            if k.lower().replace("-", "_") == str(key).lower().replace("-", "_"):
                entry = v
                break
    if entry is None and download_gib:
        entry = {"ram_gb": round(download_gib * 0.75), "arena_gb": round(download_gib * 0.55, 1)}
        estimated = True
        reasons.append("stima dal peso del file (questo modello non è nel registro del progetto)")
    if entry is None:
        return {"level": "?", "why": "niente da valutare: serve il peso del file", "host": h,
                "estimated": True}
    ram, arena = entry["ram_gb"], entry["arena_gb"]
    if download_gib and not on_disk:
        # il cancello dello spazio vale solo se c'e' da SCARICARE: un modello gia' sul disco ha bisogno
        # solo del pack (~1,5 GB), non dei suoi 60-100 GB.
        sp_ = check_space(download_gib, DATA / "models")
        if not sp_["ok"]:
            return {"level": "no", "why": f"spazio: servono ~{sp_['needed_gib']} GB, liberi {sp_['free_gib']} GB",
                    "host": h, "estimated": estimated, "ram_gb": ram, "arena_gb": arena}
    if on_disk:
        reasons.append("già sul disco")
    if h.get("ram_total_gib") is not None and h["ram_total_gib"] < ram:
        return {"level": "no", "why": f"RAM: questa taglia vuole un PC da {ram} GB, qui ce ne sono {h['ram_total_gib']}",
                "host": h, "estimated": estimated, "ram_gb": ram, "arena_gb": arena}
    if h.get("ram_total_gib") is not None and arena > h["ram_total_gib"]:
        reasons.append(f"l'arena da {arena} GB non entra nei {h['ram_total_gib']} GB di RAM: "
                       f"gli esperti arrivano dal disco, ~7-8,5 tok/s")
        return {"level": "disco", "why": "; ".join(reasons), "host": h, "estimated": estimated,
                "ram_gb": ram, "arena_gb": arena}
    reasons.append(f"arena {arena} GB su {h.get('ram_total_gib')} GB di RAM")
    return {"level": "piena", "why": "; ".join(reasons), "host": h, "estimated": estimated,
            "ram_gb": ram, "arena_gb": arena}


_SIZES: dict = {}          # repo -> {"at": epoch, "sizes": {quant: GiB}}


def quant_sizes(repo: str, max_age: float = 1800.0) -> dict:
    """{quantisation: GiB} for a repository, read from HuggingFace and cached for half an hour.

    Hard-coding these would go stale the moment the publisher adds a size; one tree request costs
    ~0.3 s and covers every quant in the repository."""
    import time as _time
    now = _time.time()
    ent = _SIZES.get(repo)
    if ent and now - ent["at"] < max_age:
        return ent["sizes"]
    try:
        grp = groups(_repo_tree(repo))
    except Exception:
        return (ent or {}).get("sizes", {})
    sizes = {k: round(sum(f.get("size") or 0 for f in v) / 2 ** 30, 1) for k, v in grp.items()}
    _SIZES[repo] = {"at": now, "sizes": sizes}
    return sizes


def key_for(repo: str, quant: str, family: str = None) -> str:
    """The name a downloaded model takes on disk.

    The original family keeps the plain quantisation name (`q2_0`), because that is what the shipped
    configurations use.  Every other family is prefixed (`swift_q2_0`), otherwise Swift's IQ3_XXS
    would collide with the original model's configuration of the same name - and the guard would
    (correctly) refuse a download that has every right to happen."""
    if family in (None, "qwen"):
        return quant.lower()
    return (f"{family}_{quant}").lower().replace("-", "_").replace("__", "_")


def family_of(repo: str) -> str:
    for e in OFFICIAL:
        if e["repo"].lower() == (repo or "").lower():
            return e["family"]
    return "qwen"
