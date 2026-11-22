"""serve/telemetry.py - hardware readings for the web app's Monitor tab (idea from PR #22 by code-martin).

A background thread samples once a second and keeps the last 60 readings of each series for the sparklines:
- GPU: NVIDIA's own NVML library (nvml.dll / libnvidia-ml.so.1, installed with every driver) through ctypes, so no
  pip package is needed: load, VRAM, temperature, power, PCIe link and throughput.  With the AMD backend (#301): the
  amdgpu driver's Linux sysfs files - load, VRAM, temperature and power.  On macOS (Metal backend): IOKit's
  IOAccelerator registry - load and VRAM; the temperature and power sensors need root (`powermetrics`), and an Apple
  Silicon GPU sits on the die, so there is no PCIe link.
- CPU, RAM, disk: `psutil` when it is installed (setup installs it); without it the CPU and RAM readings fall back to
  the OS (Windows GlobalMemoryStatusEx / GetSystemTimes, Linux /proc) and the disk rate is absent.
Anything that cannot be read is None; nothing here can stop the server.
"""
from __future__ import annotations

import collections
import ctypes
import os
import platform
import re
import struct
import subprocess
import sys
import threading
import time

HISTORY = 60


# ------------------------------------------------------------------------------------------------ NVML
class _Nvml:
    class Util(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    class Mem(ctypes.Structure):
        _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]

    def __init__(self, index=0):
        self.lib = self.dev = None
        names = ["nvml.dll", os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                                          "NVIDIA Corporation", "NVSMI", "nvml.dll")] if os.name == "nt" \
            else ["libnvidia-ml.so.1", "libnvidia-ml.so"]
        for n in names:
            try:
                self.lib = ctypes.CDLL(n)
                break
            except OSError:
                continue
        if self.lib is None:
            return
        try:
            init = getattr(self.lib, "nvmlInit_v2", None) or self.lib.nvmlInit
            if init() != 0:
                self.lib = None
                return
            h = ctypes.c_void_p()
            get = getattr(self.lib, "nvmlDeviceGetHandleByIndex_v2", None) or self.lib.nvmlDeviceGetHandleByIndex
            if get(ctypes.c_uint(index), ctypes.byref(h)) != 0:
                self.lib = None
                return
            self.dev = h
        except (AttributeError, OSError):
            self.lib = None

    def ok(self):
        return self.lib is not None and self.dev is not None

    def _uint(self, fn, *args):
        v = ctypes.c_uint()
        try:
            return v.value if getattr(self.lib, fn)(self.dev, *args, ctypes.byref(v)) == 0 else None
        except (AttributeError, OSError):
            return None

    def name(self):
        buf = ctypes.create_string_buffer(96)
        try:
            if self.lib.nvmlDeviceGetName(self.dev, buf, ctypes.c_uint(96)) == 0:
                return buf.value.decode(errors="replace")
        except (AttributeError, OSError):
            pass
        return None

    def read(self):
        out = {}
        u = self.Util()
        try:
            if self.lib.nvmlDeviceGetUtilizationRates(self.dev, ctypes.byref(u)) == 0:
                out["util"] = u.gpu
        except (AttributeError, OSError):
            pass
        m = self.Mem()
        try:
            if self.lib.nvmlDeviceGetMemoryInfo(self.dev, ctypes.byref(m)) == 0:
                out["mem_used"], out["mem_total"] = m.used, m.total
        except (AttributeError, OSError):
            pass
        out["temp"] = self._uint("nvmlDeviceGetTemperature", ctypes.c_uint(0))          # NVML_TEMPERATURE_GPU
        mw = self._uint("nvmlDeviceGetPowerUsage")
        out["power"] = mw / 1000.0 if mw is not None else None
        lim = self._uint("nvmlDeviceGetEnforcedPowerLimit")
        out["power_limit"] = lim / 1000.0 if lim is not None else None
        out["pcie_gen"] = self._uint("nvmlDeviceGetCurrPcieLinkGeneration")        # drops at idle (power saving)
        out["pcie_gen_max"] = self._uint("nvmlDeviceGetMaxPcieLinkGeneration")
        out["pcie_width"] = self._uint("nvmlDeviceGetCurrPcieLinkWidth")
        out["pcie_width_max"] = self._uint("nvmlDeviceGetMaxPcieLinkWidth")
        rx = self._uint("nvmlDeviceGetPcieThroughput", ctypes.c_uint(1))                 # NVML_PCIE_UTIL_RX_BYTES, KB/s
        tx = self._uint("nvmlDeviceGetPcieThroughput", ctypes.c_uint(0))
        out["pcie_rx_mb"] = rx / 1024.0 if rx is not None else None
        out["pcie_tx_mb"] = tx / 1024.0 if tx is not None else None
        return out


# ------------------------------------------------------------------------------------------------ AMD (Linux sysfs)
SYSFS = "/sys"


def amd_device_dir(index, sysfs=None):
    """The amdgpu sysfs folder (/sys/class/drm/renderD<N>/device) of the AMD GPU that HIP numbers `index`: the KFD
    topology's GPU nodes in order, the CPU nodes skipped, linked to their render node by drm_render_minor - the
    numbering setup's amd_gpus() and HIP_VISIBLE_DEVICES use.  None when there is no such card (or no amdgpu)."""
    base = os.path.join(sysfs or SYSFS, "class", "kfd", "kfd", "topology", "nodes")
    try:
        nodes = sorted((n for n in os.listdir(base) if n.isdigit()), key=int)
    except OSError:
        return None
    gpus = []
    for n in nodes:
        try:
            with open(os.path.join(base, n, "properties"), encoding="utf-8") as f:
                props = dict(line.strip().partition(" ")[::2] for line in f if line.strip())
            if int(props.get("gfx_target_version") or 0) == 0 or int(props.get("simd_count") or 0) == 0:
                continue
            gpus.append(props)
        except (OSError, ValueError):
            continue
    if not 0 <= index < len(gpus) or not gpus[index].get("drm_render_minor"):
        return None
    dev = os.path.join(sysfs or SYSFS, "class", "drm", "renderD" + gpus[index]["drm_render_minor"].strip(), "device")
    return dev if os.path.isdir(dev) else None


class _Amd:
    """#301: an AMD card's readings from the amdgpu driver's sysfs files (Linux; no ROCm library needed), with _Nvml's
    interface: load (gpu_busy_percent), VRAM (mem_info_vram_used / _total), and from its hwmon folder the temperature
    (temp1_input, the edge sensor, m°C), power (power1_average or power1_input, µW) and its cap (power1_cap)."""

    def __init__(self, index=0, sysfs=None):
        self.dev = amd_device_dir(index, sysfs)
        self.hwmon = None
        if self.dev:
            try:
                hw = sorted(os.listdir(os.path.join(self.dev, "hwmon")))
                self.hwmon = os.path.join(self.dev, "hwmon", hw[0]) if hw else None
            except OSError:
                pass

    def ok(self):
        return self.dev is not None

    @staticmethod
    def _int(path):
        try:
            with open(path, encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError, TypeError):
            return None

    def name(self):
        try:
            with open(os.path.join(self.dev, "product_name"), encoding="utf-8") as f:
                return f.read().strip() or "AMD Radeon"
        except (OSError, TypeError):
            return "AMD Radeon"

    @staticmethod
    def _gen(text):
        """The PCIe generation of a link-speed file's contents ("16.0 GT/s PCIe" -> 4), or None."""
        try:
            return {2.5: 1, 5.0: 2, 8.0: 3, 16.0: 4, 32.0: 5, 64.0: 6}[float(str(text).split()[0])]
        except (ValueError, TypeError, IndexError, KeyError):
            return None

    @staticmethod
    def _bdf(s):
        """True for a sysfs pci device name ("0000:03:00.0"); nothing is imported for it."""
        return (len(s) == 12 and s[4] == ":" and s[7] == ":" and s[10] == "." and s[11] in "01234567"
                and all(c in "0123456789abcdef" for c in s[0:4] + s[5:7] + s[8:10]))

    @staticmethod
    def _read(d, name):
        try:
            with open(os.path.join(d, name), encoding="utf-8") as f:
                return f.read().strip()
        except (OSError, TypeError):
            return None

    def _hops(self):
        """The PCIe devices between the root port and this card, the card last: the sysfs path names every
        hop (a card behind a bridge chain has more than one; a directly attached card has one)."""
        out, prefix = [], []
        for part in os.path.realpath(self.dev or "").split("/"):
            prefix.append(part)
            if self._bdf(part):
                out.append("/".join(prefix))
        return out

    def link(self):
        """The PCIe link the card actually gets: the **narrowest/slowest hop** between the root port and the card,
        from each hop's `max_link_speed` / `max_link_width` (the capability, so a power-saving downgrade or a Gen3
        slot cannot make it read low).  A card that is Gen4 on its own hop but sits behind a Gen3 root port really
        runs at Gen3, and that is the number a PCIe bandwidth budget needs.
        `pcie_own_gen` keeps the card's own hop aside: the gap between the two is what a user has to see.

        The bottleneck is only claimed when **every** hop of the path could be read; `pcie_path` reports how many
        of them were ("4/4").  A kernel or a container that hides part of /sys/devices would otherwise drop the
        unreadable hops in silence and report the card's own Gen4 hop as the whole path - i.e. be optimistic
        exactly where it matters.  When the walk is incomplete the reading falls back to the card's own negotiated
        link and pcie_path says so."""
        hops = self._hops()
        gens, widths, read = [], [], 0
        for d in hops:
            g = self._gen(_Amd._read(d, "max_link_speed"))
            w = self._int(os.path.join(d, "max_link_width"))
            read += 1 if (g is not None or w is not None) else 0
            if g:
                gens.append(g)
            if w:
                widths.append(w)
        own = self.dev or ""
        own_gen = self._gen(_Amd._read(own, "current_link_speed"))
        whole = bool(hops) and read == len(hops)
        gen = min(gens) if (whole and gens) else own_gen
        width = min(widths) if (whole and widths) else self._int(os.path.join(own, "current_link_width"))
        return {"pcie_gen": gen, "pcie_gen_max": gen, "pcie_own_gen": own_gen, "pcie_width": width,
                "pcie_path": "%d/%d" % (read, len(hops))}


    def read(self):
        out = {"util": self._int(os.path.join(self.dev, "gpu_busy_percent")),
               "mem_used": self._int(os.path.join(self.dev, "mem_info_vram_used")),
               "mem_total": self._int(os.path.join(self.dev, "mem_info_vram_total"))}
        if self.hwmon:
            t = self._int(os.path.join(self.hwmon, "temp1_input"))
            out["temp"] = t / 1000.0 if t is not None else None
            p = self._int(os.path.join(self.hwmon, "power1_average"))
            if p is None:
                p = self._int(os.path.join(self.hwmon, "power1_input"))
            out["power"] = p / 1e6 if p is not None else None
            cap = self._int(os.path.join(self.hwmon, "power1_cap"))
            out["power_limit"] = cap / 1e6 if cap is not None else None
        out.update(self.link())
        return out


def metal_working_set():
    """The Apple GPU's memory budget in bytes: MTLCreateSystemDefaultDevice's recommendedMaxWorkingSetSize, through
    the Metal framework and objc_msgSend (no PyObjC) - the same property metal/src/mtl_rt.mm reads for the engine
    (its "GPU working set" log line).  None off macOS, or when it cannot be read: a selector the device does not
    answer would raise an Objective-C exception no ctypes call can catch, so the class is asked first."""
    if sys.platform != "darwin":
        return None
    try:
        metal = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
        objc = ctypes.CDLL("/usr/lib/libobjc.dylib")
        metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.object_getClass.argtypes = [ctypes.c_void_p]
        objc.object_getClass.restype = ctypes.c_void_p
        objc.class_respondsToSelector.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc.class_respondsToSelector.restype = ctypes.c_ubyte
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        objc.objc_msgSend.restype = ctypes.c_ulonglong
        dev = metal.MTLCreateSystemDefaultDevice()
        if not dev:
            return None
        sel = objc.sel_registerName(b"recommendedMaxWorkingSetSize")
        if not objc.class_respondsToSelector(objc.object_getClass(dev), sel):
            return None
        return int(objc.objc_msgSend(ctypes.c_void_p(dev), ctypes.c_void_p(sel))) or None
    except (OSError, AttributeError, ValueError):
        return None


class _Metal:
    """macOS: an Apple GPU's readings from the IOKit registry (`ioreg -l -w0 -r -c IOAccelerator`, 22 ms), with
    _Nvml's interface: the load and the memory are the driver's PerformanceStatistics of the index'th accelerator
    node - Device Utilization % and the in-use system memory in bytes.  The total is the device's Metal working set,
    the budget one app gets of the unified memory.  No temperature or power reading exists without root
    (`powermetrics`), and an Apple Silicon GPU sits on the die, so the PCIe cards have nothing to show."""
    note = ("no GPU temperature or power reading without root (powermetrics), and an Apple Silicon GPU sits on the "
            "die, so there is no PCIe link to show; the engine's own figures are in its log")
    cmd = ("ioreg", "-l", "-w0", "-r", "-c", "IOAccelerator")

    def __init__(self, index=0, run=None):
        self.index = index
        self._run = run or self._ioreg
        self.nodes = len(self._blocks())
        self._name = None
        b = self._block()
        if b:
            m = re.search(r'"model" = "([^"]+)"', b)
            self._name = m.group(1) if m else None

    @staticmethod
    def _ioreg():
        try:
            return subprocess.run(list(_Metal.cmd), capture_output=True, text=True, timeout=10).stdout or ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def _blocks(self):
        """The accelerator nodes, in the registry's order: every node that carries a PerformanceStatistics."""
        try:
            out = self._run() or ""
        except OSError:                     # ioreg missing, or a caller's runner that raises
            return []
        return [b for b in re.split(r"^\s*\+-o ", out, flags=re.M) if '"PerformanceStatistics"' in b]

    def _block(self):
        b = self._blocks()
        return b[self.index] if 0 <= self.index < len(b) else None

    def ok(self):
        return self.index < self.nodes

    def name(self):
        return self._name

    def read(self):
        b = self._block()
        if b is None:
            return {}

        def num(key):
            m = re.search(r'"%s"=([0-9.]+)' % re.escape(key), b)
            return float(m.group(1)) if m else None

        out = {}
        u = num("Device Utilization %")
        if u is None:                      # older chips report only the renderer and the tiler
            r, t = num("Renderer Utilization %"), num("Tiler Utilization %")
            u = max(v for v in (r, t) if v is not None) if (r is not None or t is not None) else None
        out["util"] = int(u) if u is not None else None
        used = num("In use system memory")
        out["mem_used"] = int(used) if used is not None else None
        out["mem_total"] = metal_working_set()
        return out


class _AmdWindows(_Amd):
    """#301 on Windows: an AMD card's readings through the OS GPU performance counters, read with PDH (the API
    Task Manager uses - a query is microseconds, WMI's was 5-7 SECONDS a read and stole CPU from the expert
    pool): GPU load (GPU Engine counters, summed over every process × engine), VRAM (GPU Adapter Memory
    dedicated), Total Committed.  Temperature and power are NOT in the OS counters for AMD; when AIDA64 runs
    with its shared memory on they come from there (its 4 KB XML page), otherwise they stay None.  Nothing here
    can stop the server: every read is guarded."""

    def __init__(self, index=0):
        self.dev = None
        self._ok = False
        self._amd_index = index
        self._pdh = self._q_util = self._q_mem = self._q_tc = None
        self._h_util = self._h_mem = self._h_tc = None   # read() checks them when PDH failed
        # The card's own VRAM size: the display driver's registry HardwareInformation.qwMemorySize - the same
        # place setup reads it (AdapterRAM is a signed int, -1048576 on a 24 GB card).
        self._vram_total = None
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
                        try:
                            self._vram_total = int(winreg.QueryValueEx(sub, "HardwareInformation.qwMemorySize")[0])
                        except (OSError, ValueError, TypeError):
                            pass
                        winreg.CloseKey(sub)
                        break
                except OSError:
                    pass
                winreg.CloseKey(sub)
                i += 1
        except Exception:
            pass
        # PDH: one query per counter set, opened once.  Wildcard instances (*) so a query sees every GPU engine
        # instance at once; the values come back as a (count, values) pair of floats.
        try:
            pdh = ctypes.WinDLL("pdh")
            pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p]
            pdh.PdhOpenQueryW.restype = ctypes.c_uint
            pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p,
                                                  ctypes.c_void_p]
            pdh.PdhAddEnglishCounterW.restype = ctypes.c_uint
            pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            pdh.PdhCollectQueryData.restype = ctypes.c_uint
            pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint),
                                                         ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]
            pdh.PdhGetFormattedCounterArrayW.restype = ctypes.c_uint
            pdh.PdhCollectQueryDataEx.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p]
            self.pdh = pdh
            PDH_MORE_DATA = 0x800007D2
            self._PDH_MORE_DATA = PDH_MORE_DATA

            def open_query(paths):
                q = ctypes.c_void_p()
                if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
                    return None, []
                handles = []
                for p in paths:
                    h = ctypes.c_void_p()
                    if pdh.PdhAddEnglishCounterW(q, p, None, ctypes.byref(h)) == 0:
                        handles.append(h)
                return q, handles

            self._q_util, self._h_util = open_query(
                [r"\GPU Engine(*)\Utilization Percentage"])
            self._q_mem, self._h_mem = open_query(
                [r"\GPU Adapter Memory(*)\Dedicated Usage"])
            self._q_tc, self._h_tc = open_query(
                [r"\GPU Adapter Memory(*)\Total Committed"])
            self._ok = bool(self._h_util and self._h_mem) and index < len(windows_amd_cards())
            if self._ok:
                # first sample: rates need two, the formatted array below does the rest
                pdh.PdhCollectQueryData(self._q_util)
                pdh.PdhCollectQueryData(self._q_mem)
        except Exception:
            self.pdh = None

        # AIDA64's shared memory (File / Preferences / External Applications / Shared Memory), when the user runs
        # it: a 4 KB XML page (<temp><id>TGPU1</id><label>GPU</label><value>36</value></temp>...).  It is the only
        # source on Windows that gives an AMD card's temperature (and more sensors); without it temp stays None.
        try:
            k32 = ctypes.WinDLL("kernel32")
            k32.OpenFileMappingW.restype = ctypes.c_void_p
            k32.MapViewOfFile.restype = ctypes.c_void_p
            k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
            self._k32 = k32
        except Exception:
            self._k32 = None

    def _array(self, handle):
        """Every instance's value of one wildcard counter as {instance_name: float} - PDH's formatted array,
        grown until PDH stops saying MORE_DATA.  {} when anything fails."""
        try:
            need = ctypes.c_uint(0)
            count = ctypes.c_uint(0)
            PDH_FMT_DOUBLE = 0x00000200
            if self.pdh.PdhGetFormattedCounterArrayW(handle, PDH_FMT_DOUBLE, ctypes.byref(need),
                                                     ctypes.byref(count), None) != self._PDH_MORE_DATA:
                return {}
            buf = ctypes.create_string_buffer(need.value)
            if self.pdh.PdhGetFormattedCounterArrayW(handle, PDH_FMT_DOUBLE, ctypes.byref(need),
                                                     ctypes.byref(count), buf) != 0:
                return {}
            # PDH_FMT_COUNTERVALUE_ITEM_W here packs 24 bytes/item: [0:8] LPWSTR szName, [8:12] LONG status,
            # [12:16] pad, [16:24] double value - then every name inline after the array (verified on this PC:
            # 2 items = 48 bytes + 2 x 68-byte names = the sizing call's 184).
            names_start = count.value * 24
            names = []
            if names_start + 2 <= need.value:
                names = [s for s in ctypes.wstring_at(ctypes.addressof(buf) + names_start,
                                                      (need.value - names_start) // 2).split("\x00") if s]
            out = {}
            for i in range(count.value):
                off = i * 24
                if off + 24 > need.value:
                    break
                name = names[i] if i < len(names) else f"item{i}"
                out[name] = struct.unpack_from("<d", buf, off + 16)[0]
            return out
        except Exception:
            return {}

    def _aida_read(self):
        """AIDA64's shared memory page as {id: value}, or None.

        Keyed by AIDA64's own sensor id, never by the label: the label "GPU" is BOTH the edge temperature
        (TGPU1) and the board power (PGPU1), so a label-keyed dict showed the power (94 W) as the temperature
        ("94 °C").  The ids are unambiguous - T* temperature, F* fan, P* power, C* current, V* voltage, S* usage.
        The page grows with the sensors AIDA64 exports (a 4 KB page is the old size): read the whole
        mapping, and let the regex ignore the truncated last block instead of depending on closing tags."""
        if self._k32 is None:
            values = {}
        else:
            values = {}
            try:
                h = self._k32.OpenFileMappingW(0x0004, False, "AIDA64_SensorValues")
                if h:
                    p = self._k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
                    if p:
                        try:
                            size = self._mapped_size(p) or 4096
                            raw = ctypes.string_at(p, min(size, 1 << 20))   # the mapping, never past it
                        except OSError:
                            raw = b""
                        self._k32.UnmapViewOfFile(p)
                        values = self._aida_parse(raw.decode("utf-8", "replace"))
                    self._k32.CloseHandle(h)
            except Exception:
                values = {}
        # AIDA64 sizes its shared-memory block when it starts: a GPU sensor selected later
        # is in the Registry export (if enabled) but not in the old block.  Merge it.
        if not any(k.startswith(("TGPU", "PGPU", "FGPU", "VGPU")) for k in values):
            values.update(self._aida_registry())
        return values or None

    @staticmethod
    def _aida_parse(text):
        """AIDA64's XML-ish page as {sensor id: value string}."""
        return {sid: value.strip() for sid, _label, value in
                re.findall(r"<id>([^<]+)</id><label>([^<]*)</label><value>([^<]*)</value>", text)}

    def _aida_registry(self):
        """AIDA64's Registry export (Preferences > Hardware Monitoring > External
        Applications), the same sensor ids as the shared memory page."""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\FinalWire\AIDA64\SensorValues") as key:
                out, index = {}, 0
                while True:
                    try:
                        name, value, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    out[str(name)] = str(value)
                    index += 1
                return out
        except OSError:
            return {}

    def _mapped_size(self, address):
        """The size of the AIDA64 shared-memory mapping (4 KB on old builds, more when more
        sensors are exported); 0 when the OS cannot tell us."""
        class _Mbi(ctypes.Structure):
            _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", ctypes.c_uint32), ("PartitionId", ctypes.c_uint16),
                        ("Pad", ctypes.c_uint16), ("RegionSize", ctypes.c_size_t),
                        ("State", ctypes.c_uint32), ("Protect", ctypes.c_uint32), ("Type", ctypes.c_uint32)]
        info = _Mbi()
        try:
            query = self._k32.VirtualQuery
            query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Mbi), ctypes.c_size_t]
            query.restype = ctypes.c_size_t
            return int(info.RegionSize) if query(ctypes.c_void_p(address), ctypes.byref(info),
                                                  ctypes.sizeof(info)) else 0
        except Exception:
            return 0

    def ok(self):
        return self._ok

    def name(self):
        try:
            cards = windows_amd_cards()
            if cards:
                return cards[0]["name"]      # the registry: "AMD Radeon RX 7900 XTX"
        except Exception:
            pass
        try:
            import wmi  # type: ignore
            for r in wmi.WMI(namespace="root/cimv2").Win32_VideoController():
                if "AMD" in (r.Name or "") or "Radeon" in (r.Name or ""):
                    return r.Name
        except Exception:
            pass
        return "AMD Radeon"

    def read(self):
        out = {}
        try:
            self.pdh.PdhCollectQueryData(self._q_util)
            self.pdh.PdhCollectQueryData(self._q_mem)
            self.pdh.PdhCollectQueryData(self._q_tc)
        except Exception:
            pass
        # ---- GPU load: sum of Utilization Percentage over every process × engine instance
        from serve.windows_gpu_identity import amd_luid, adapter_values
        if not hasattr(self, '_adapter_luid'):
            self._adapter_luid = amd_luid(self._amd_index)
        util_all = self._array(self._h_util[0]) if self._h_util else {}
        mem_all = self._array(self._h_mem[0]) if self._h_mem else {}
        if not self._adapter_luid:
            # DXGI can enumerate only the software adapter in a remote/headless session
            # (the card is still in the PDH counters); the adapter's own memory instance
            # - the one without a pid_ prefix - carries the LUID the counters are keyed by.
            own = next((name for name in mem_all if "pid_" not in name.lower()), "")
            found = re.match(r"(luid_0x[0-9a-f]+_0x[0-9a-f]+)", own, re.I)
            if found:
                self._adapter_luid = found.group(1)
        util = adapter_values(util_all, self._adapter_luid)
        if util:
            out["util"] = min(100.0, sum(util.values()))

        # ---- VRAM: DedicatedUsage (bytes on the card) per adapter, the luid_…_phys_0 instance without a pid_
        # prefix is the adapter's own; the card's size comes from the driver's registry entry.
        mem = adapter_values(mem_all, self._adapter_luid)
        for name, v in mem.items():
            if "pid_" not in name.lower():
                out["mem_used"] = int(v)
                break
        if self._vram_total:
            out["mem_total"] = self._vram_total

        # ---- Temperature, hotspot, fan and power from AIDA64's shared memory, when the user runs it: Windows
        # exposes none of these for an AMD card.  Picked by AIDA64's sensor ID (its label "GPU" is ambiguous:
        # it is the edge temperature as TGPU1 and the board power as PGPU1 - keying on the label is what showed
        # the power as a temperature).
        sensors = self._aida_read() or {}

        def pick(sid):
            v = sensors.get(sid)
            if v in (None, ""):
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        for key, sid in (("temp", "TGPU1"), ("temp_hotspot", "TGPU1HOT"), ("vram_temp", "TGPU1MEM"),
                         ("fan_rpm", "FGPU1"), ("power", "PGPU1"), ("volt", "VGPU1"),
                         ("cpu_temp", "TCPUPKG")):
            v = pick(sid)
            if v is not None:
                out[key] = v
        # CPU power: AIDA64's "CPU Package" (PCPUPKG).  Its other CPU power ids are not usable here - "CPU"
        # (PCPU) was sampled over 24 s and returned 10, 33, 63, 124, 152, 188, 244, 277 and 303 W in no
        # relation to the load, while PCPUPKG held 114-121 W and PCPUIAC 100-114 W.  PCPUPKG is the stable
        # AIDA64 reading, so the tile keeps it; PCPU is never substituted for it.
        for sid in ("PCPUPKG", "PCPU"):
            v = pick(sid)
            if v is not None:
                out["cpu_power"] = v
                break
        # Missing AIDA64 GPU sensors may be read directly from AMD's driver.
        # Queries only: no clock/power/fan setters or PMLog sampling changes.
        if any(key not in out for key in ('temp','temp_hotspot','vram_temp','power','volt')):
            try:
                if not hasattr(self, '_sensor_reader'):
                    from serve.amd_sensors import Reader
                    self._sensor_reader = Reader(self._amd_index)
                for key, value in self._sensor_reader.read().items():
                    out.setdefault(key, value)
            except (OSError, ValueError, AttributeError, TypeError):
                self._sensor_reader = None
        # The negotiated PCIe link, from Windows' own PnP device properties (serve/pcie_link.py): the one real
        # PCIe fact an AMD card exposes in user mode.  The module refreshes it on its own thread, so this read
        # never waits on PowerShell.  Keys get the gpu_ prefix (-> gpu_pcie_gen / _width / _gen_max).
        try:
            from serve import pcie_link
            pcie_link.start()
            link = pcie_link.current()
            if link:
                out["pcie_gen"], out["pcie_width"], out["pcie_gen_max"] = link["gen"], link["width"], link["gen_max"]
        except Exception:  # noqa: BLE001 - the link is a bonus, never a reason to fail a sample
            pass
        # mem_total here is the card's size from the driver's registry (HardwareInformation.qwMemorySize);
        # mem_used is the PDH DedicatedUsage.  The old Total Committed read is gone: it added what spilled
        # to shared system memory and showed 69 GiB on a 24 GB card.
        return out

def gpu_reader(index=0, amd=False):
    """The card's readings: NVML (NVIDIA), the amdgpu sysfs files with the AMD backend (#301), or IOKit's
    IOAccelerator registry on macOS (Metal backend).  `amd` comes first: no Mac runs the HIP backend, and the
    tests' AMD trees are read on a Mac too."""
    if amd:
        # Windows has no amdgpu sysfs for a real card: use the OS GPU counters instead (#301).
        # A readable sysfs tree (Linux, or a test's fake SYSFS) is read as before.
        if os.name == "nt" and amd_device_dir(index) is None:
            return _AmdWindows(index)
        return _Amd(index)
    return _Metal(index) if sys.platform == "darwin" else _Nvml(index)


_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def windows_display_adapters(vendor=None) -> list:
    """#1587: the display adapters Windows has drivers for, from the registry's display class (no subprocess, no vendor
    library): [{"name", "provider", "driver", "vram_bytes"}] in the class's order.  `vendor`: "amd", "nvidia" or
    "intel" keeps that vendor's cards.  [] off Windows or when nothing can be read."""
    if os.name != "nt":
        return []
    try:
        import winreg
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS)
    except OSError:
        return []
    out = []
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(root, i)
        except OSError:
            break
        i += 1
        if not sub.isdigit():
            continue
        try:
            k = winreg.OpenKey(root, sub)
        except OSError:
            continue

        def val(name, k=k):
            try:
                return winreg.QueryValueEx(k, name)[0]
            except OSError:
                return None
        name = val("DriverDesc")
        if not isinstance(name, str) or not name.strip():
            continue
        mem = val("HardwareInformation.qwMemorySize")
        if mem is None:
            mem = val("HardwareInformation.MemorySize")
        if isinstance(mem, (bytes, bytearray)):
            mem = int.from_bytes(bytes(mem[:8]), "little") if mem else None
        out.append({"name": name.strip(), "provider": str(val("ProviderName") or ""), "driver": val("DriverVersion"),
                    "vram_bytes": mem if isinstance(mem, int) and mem > 0 else None})
    if vendor:
        keys = {"amd": ("advanced micro devices", "amd", "radeon"), "nvidia": ("nvidia",), "intel": ("intel",)}[vendor]
        out = [a for a in out if any(s in (a["provider"] + " " + a["name"]).lower() for s in keys)]
    return out


def windows_amd_cards(adapters=None) -> list:
    """The AMD cards HIP runs on, as windows_display_adapters lists them.  A Ryzen's integrated Radeon is listed too
    (512 MiB on a Ryzen 5 7600): beside a card with 2 GiB or more it is left out (an APU alone keeps it)."""
    cards = windows_display_adapters("amd") if adapters is None else adapters
    return [c for c in cards if (c["vram_bytes"] or 0) >= 2 << 30] or cards


def free_vram_mib(index=0, amd=False):
    """Free VRAM of a card in MiB, or None when it cannot be read."""
    g = gpu_reader(index, amd)
    if not g.ok():
        return None
    r = g.read()
    if r.get("mem_total") is None or r.get("mem_used") is None:
        return None
    return int((r["mem_total"] - r["mem_used"]) >> 20)


# ------------------------------------------------------------------------------------------------ CPU / RAM
def _cpu_topology(root: str = "/sys/devices/system"):
    """(sockets, NUMA nodes) of this computer: how many CPU packages it has and how many memory nodes (None where it cannot be read).
    Linux reads /sys, Windows asks GetLogicalProcessorInformationEx / GetNumaHighestNodeNumber, macOS asks sysctl (Apple silicon and every Mac
    sold so far: one package, no NUMA)."""
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            needed = ctypes.c_ulong(0)
            kernel32.GetLogicalProcessorInformationEx(3, None, ctypes.byref(needed))          # RelationProcessorPackage
            buf = ctypes.create_string_buffer(needed.value)
            sockets = None
            if needed.value and kernel32.GetLogicalProcessorInformationEx(3, buf, ctypes.byref(needed)):
                sockets, offset = 0, 0
                while offset + 8 <= needed.value:
                    relationship = int.from_bytes(buf.raw[offset:offset + 4], "little")
                    size = int.from_bytes(buf.raw[offset + 4:offset + 8], "little")
                    if size <= 0:
                        break
                    sockets += 1 if relationship == 3 else 0
                    offset += size
            high = ctypes.c_ulong(0)
            numa = high.value + 1 if kernel32.GetNumaHighestNodeNumber(ctypes.byref(high)) else None
            return (sockets or None), numa
        if sys.platform == "darwin":
            import subprocess
            out = subprocess.run(["sysctl", "-n", "hw.packages"], capture_output=True, text=True, timeout=5).stdout.strip()
            return (int(out) if out.isdigit() else 1), None
        import glob
        packages = set()
        for f in glob.glob(os.path.join(root, "cpu", "cpu[0-9]*", "topology", "physical_package_id")):
            try:
                packages.add(open(f, encoding="utf-8").read().strip())
            except OSError:
                continue
        nodes = len(glob.glob(os.path.join(root, "node", "node[0-9]*")))
        return (len(packages) or None), (nodes or None)
    except Exception:                                        # noqa: BLE001 - a missing figure is shown as missing, never guessed
        return None, None


def _cpu_name():
    if os.name == "nt":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            return winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    elif os.path.exists("/proc/cpuinfo"):
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="replace"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or None


def _read_sys(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _board_info():
    """The motherboard the machine actually has (Linux DMI; empty elsewhere).

    The dashboard's "PCH · Motherboard" tile used to be blank on Linux even
    though the kernel exposes both the board name and the PCH temperature.
    """
    if os.name == "nt" or sys.platform == "darwin":
        return {"board_vendor": None, "board_name": None, "board_product": None, "bios_version": None}
    return {
        "board_vendor": _read_sys("/sys/class/dmi/id/board_vendor"),
        "board_name": _read_sys("/sys/class/dmi/id/board_name"),
        "board_product": _read_sys("/sys/class/dmi/id/product_name"),
        "bios_version": _read_sys("/sys/class/dmi/id/bios_version"),
    }


def _linux_thermals(ps):
    """(cpu_max, cpu_package_mean, pch, nvme) from the kernel's hwmon tree.

    psutil exposes `coretemp` (Intel), `k10temp`/`zenpower` (AMD), the PCH
    (`pch_*`) and NVMe sensors on Linux.  Only values the kernel really
    reports are returned; a missing sensor stays None and the dashboard says
    so instead of inventing a number.
    """
    try:
        groups = ps.sensors_temperatures() or {}
    except (AttributeError, OSError, RuntimeError):
        return None, None, None, None
    packages, cores, pch, nvme = [], [], [], []
    for name, entries in groups.items():
        low = str(name or "").lower()
        for entry in entries or []:
            try:
                value = float(entry.current)
            except (TypeError, ValueError):
                continue
            label = str(getattr(entry, "label", "") or "").strip().lower()
            if low in ("coretemp", "k10temp", "zenpower") or low.startswith(("cpu", "soc")):
                if "package" in label or label in ("tctl", "tdie", "package"):
                    packages.append(value)
                else:
                    cores.append(value)
            elif "pch" in low or "pch" in label:
                pch.append(value)
            elif "nvme" in low and (not label or label == "composite"):
                nvme.append(value)
    cpu = max(packages or cores) if (packages or cores) else None
    package_mean = sum(packages) / len(packages) if packages else None
    return cpu, package_mean, max(pch) if pch else None, max(nvme) if nvme else None


class _RaplPower:
    """CPU package power from the kernel's RAPL counters (Linux, no root needed once readable).

    `energy_uj` is a monotonically increasing microjoule counter; power is the
    delta over time.  The counter wraps at `max_energy_range_uj`, so a wrap is
    added back instead of producing a negative (or absurd) wattage.
    """

    def __init__(self, root="/sys/class/powercap"):
        self.paths = []
        self.prev = {}
        self.prev_t = None
        self.note = None
        try:
            names = sorted(os.listdir(root))
        except OSError:
            names = []
        for name in names:
            if not re.fullmatch(r"[a-z0-9_-]+-rapl:\d+", name):
                continue
            folder = os.path.join(root, name)
            energy = os.path.join(folder, "energy_uj")
            if not os.path.exists(energy):
                continue
            try:
                with open(os.path.join(folder, "max_energy_range_uj"), encoding="ascii") as f:
                    maximum = int(f.read().strip())
            except (OSError, ValueError):
                maximum = None
            self.paths.append((energy, maximum))
        if not self.paths:
            self.note = "RAPL non disponibile su questo kernel"

    def read(self):
        if not self.paths:
            return None
        now = time.monotonic()
        values = []
        for path, maximum in self.paths:
            try:
                with open(path, encoding="ascii") as f:
                    values.append((path, int(f.read().strip()), maximum))
            except PermissionError:
                self.note = "richiede permessi kernel (RAPL)"
                return None
            except (OSError, ValueError):
                continue
        if not values:
            self.note = "contatori RAPL non leggibili"
            return None
        previous, previous_t = self.prev, self.prev_t
        self.prev = {path: value for path, value, _ in values}
        self.prev_t = now
        if previous_t is None or not previous:
            self.note = "lettura iniziale"
            return None
        elapsed = now - previous_t
        if elapsed <= 0:
            return None
        joules = 0.0
        for path, value, maximum in values:
            old = previous.get(path)
            if old is None:
                continue
            delta = value - old
            if delta < 0 and maximum:
                delta += maximum
            if delta >= 0:
                joules += delta
        self.note = None
        return round(joules / 1e6 / elapsed, 1)


class _CpuRamFallback:
    """CPU load and RAM without psutil."""

    def __init__(self):
        self.prev = self._times()

    def _times(self):
        if os.name == "nt":
            idle, kern, user = (ctypes.c_ulonglong() for _ in range(3))
            if ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                return idle.value, kern.value + user.value           # kernel time includes idle
            return None
        try:
            f = [int(x) for x in open("/proc/stat").readline().split()[1:]]
            return f[3] + f[4], sum(f)
        except (OSError, ValueError):
            return None

    def cpu(self):
        cur = self._times()
        prev, self.prev = self.prev, cur
        if not cur or not prev or cur[1] == prev[1]:
            return None
        return max(0.0, min(100.0, 100.0 * (1 - (cur[0] - prev[0]) / (cur[1] - prev[1]))))

    @staticmethod
    def ram():
        if os.name == "nt":
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return m.ullTotalPhys - m.ullAvailPhys, m.ullTotalPhys
            return None, None
        try:
            info = dict(line.split(":", 1) for line in open("/proc/meminfo"))
            total = int(info["MemTotal"].split()[0]) * 1024
            avail = int(info["MemAvailable"].split()[0]) * 1024
            return total - avail, total
        except (OSError, KeyError, ValueError):
            return None, None


# ------------------------------------------------------------------------------------------------ the sampler
class Telemetry:
    def __init__(self, extra=None, gpu_index=0, gpu_indices=None, amd=False):
        """`extra()` -> dict of more series to record each second (the server's tok/s).  `gpu_index`: the card the
        engine runs on, numbered as nvidia-smi and NVML number them (by PCI bus); `gpu_indices`: all of them when
        the model is split across several (issue #112) - the gpu_* readings are then their total (memory, power,
        PCIe traffic), mean (load) or hottest (temperature), and "gpus" has each card's own.  `amd`: the AMD backend's
        cards, numbered as HIP numbers them, read from sysfs (#301)."""
        self.extra = extra
        self.lock = threading.Lock()
        self.now: dict = {}
        self.hist = collections.defaultdict(lambda: collections.deque(maxlen=HISTORY))
        idx = list(gpu_indices) if gpu_indices and len(gpu_indices) > 1 else [gpu_index]
        self.gpus = [(i, gpu_reader(i, amd)) for i in idx]
        self.gpus = [(i, g) for i, g in self.gpus if g.ok()] or self.gpus[:1]
        self.gpu = self.gpus[0][1]
        try:
            import psutil  # noqa: F401
            self.ps = sys.modules["psutil"]
        except ImportError:
            self.ps = None
        self.fallback = _CpuRamFallback()
        self.rapl = _RaplPower() if os.name != "nt" and sys.platform != "darwin" else None
        gpu_name = " + ".join(g.name() or "?" for _, g in self.gpus) if self.gpu.ok() else None
        win_amd = None
        if gpu_name is None and amd and os.name == "nt":
            # #1587: no readings for an AMD card on Windows yet, but its name (and VRAM size) are in the registry, so the
            # dashboard and strata_bench do not call the run "CPU only".  The class order is taken as HIP's order.
            cards = windows_amd_cards()
            win_amd = [cards[i] for i in idx if 0 <= i < len(cards)] or cards[:1]
            gpu_name = " + ".join(c["name"] for c in win_amd) if win_amd else None
        # the macOS reader knows the device's working set (the VRAM budget of the unified memory); None elsewhere
        vram_total = None
        if win_amd is None and isinstance(self.gpu, _Metal) and self.gpu.ok():
            ws = metal_working_set()
            vram_total = ws >> 20 if ws else None
        self.static = {
            "gpu_name": gpu_name,
            "gpu_vram_total_mib": (sum(c["vram_bytes"] for c in win_amd) >> 20
                                   if win_amd and all(c["vram_bytes"] for c in win_amd) else vram_total),
            "gpu_count": len(self.gpus),
            # #1380: the AMD readings are the amdgpu driver's Linux sysfs files; a Windows AMD card has none yet, and the
            # dashboard said "not readable (NVML)" or showed empty tiles with no word why
            "gpu_note": ("no GPU load or VRAM readings for AMD cards on Windows yet (Linux reads them from the amdgpu "
                         "driver); the engine's own VRAM figures are in its log" if amd and not self.gpu.ok()
                         else getattr(self.gpu, "note", None)),
            "cpu_name": _cpu_name(),
            "cores": (self.ps.cpu_count(logical=False) if self.ps else None) or None,
            "threads": os.cpu_count(),
            "sockets": _cpu_topology()[0],
            "numa_nodes": _cpu_topology()[1],
            "psutil": self.ps is not None,
            **_board_info(),
        }
        if amd:
            # the gfx architecture of the cards, for the dashboard's arch field (live line).
            # The probe can take ~8 s: run it beside the server, never before it listens.
            self.static["gpu_archs"] = []

            def probe_archs():
                try:
                    import setup as strata_setup
                    probe = strata_setup.ROOT / "engine" / ("strata-device.exe" if os.name == "nt" else "strata-device")
                    env = dict(os.environ)
                    env["PATH"] = os.pathsep.join([str(d) for d in strata_setup.hip_lib_dirs(probe.parent)] + [env.get("PATH", "")])
                    result = subprocess.run([str(probe), "--list-devices"], capture_output=True, text=True, timeout=8,
                                            cwd=str(probe.parent), env=env,
                                            creationflags=0x08000000 if os.name == "nt" else 0)
                    devices = strata_setup.hip_devices(text=result.stdout) if result.returncode == 0 else []
                    archs = [g["arch"] for g in (devices or [])
                             if g["index"] in idx and re.fullmatch(r"gfx[0-9a-f]+", g["arch"])]
                except (OSError, ValueError, RuntimeError, ImportError, AttributeError, subprocess.TimeoutExpired):
                    archs = []
                with self.lock:
                    self.static["gpu_archs"] = archs

            threading.Thread(target=probe_archs, daemon=True, name="strata-gpu-arch").start()
        self.last_efficiency = None
        self._disk_prev = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _disk(self):
        if not self.ps:
            return None, None
        try:
            c = self.ps.disk_io_counters()
        except (OSError, RuntimeError):
            return None, None
        if c is None:
            self._disk_prev=None
            return None,None
        t = time.time()
        prev, self._disk_prev = self._disk_prev, (t, c.read_bytes, c.write_bytes)
        if prev is None or t <= prev[0]:
            return None, None
        dt = t - prev[0]
        return (c.read_bytes - prev[1]) / dt / 2**20, (c.write_bytes - prev[2]) / dt / 2**20

    def sample(self):
        s = {}
        if self.gpu.ok():
            reads = [(i, g.read()) for i, g in self.gpus]
            g = dict(reads[0][1])
            if len(reads) > 1:
                def vals(k):
                    return [r[k] for _, r in reads if r.get(k) is not None]
                for k in ("mem_used", "mem_total", "power", "power_limit", "pcie_rx_mb", "pcie_tx_mb"):
                    v = vals(k)
                    g[k] = sum(v) if v else None
                u = vals("util")
                g["util"] = sum(u) / len(u) if u else None
                t = vals("temp")
                g["temp"] = max(t) if t else None
                s["gpus"] = [{"index": i, "name": reader.name(), "util": r.get("util"), "mem_used": r.get("mem_used"),
                              "mem_total": r.get("mem_total"), "temp": r.get("temp"), "power": r.get("power")}
                             for (i, r), (_, reader) in zip(reads, self.gpus)]
            s.update({f"gpu_{k}": v for k, v in g.items()
                      if k not in ("cpu_temp", "cpu_power")})
            # the AMD reader also reads AIDA64's CPU sensors: those are not GPU values
            for k in ("cpu_temp", "cpu_power"):
                if g.get(k) is not None:
                    s[k] = g[k]
        if self.ps:
            try:
                s["cpu"] = self.ps.cpu_percent(interval=None)
                vm = self.ps.virtual_memory()
                s["ram_used"], s["ram_total"] = vm.total - vm.available, vm.total
            except (OSError, RuntimeError):
                pass
            if os.name != "nt" and sys.platform != "darwin":
                cpu_temp, cpu_avg, pch, nvme = _linux_thermals(self.ps)
                if cpu_temp is not None:
                    s.setdefault("cpu_temp", cpu_temp)
                if cpu_avg is not None:
                    s["cpu_temp_avg"] = cpu_avg
                if pch is not None:
                    s["pch_temp"] = pch
                if nvme is not None:
                    s["nvme_temp"] = nvme
        else:
            s["cpu"] = self.fallback.cpu()
            s["ram_used"], s["ram_total"] = self.fallback.ram()
        if self.rapl is not None:
            power = self.rapl.read()
            if power is not None:
                s.setdefault("cpu_power", power)
            if self.rapl.note:
                s["cpu_power_note"] = self.rapl.note
        s["disk_read_mb"], s["disk_write_mb"] = self._disk()
        if self.extra:
            try:
                s.update(self.extra())
            except Exception:  # noqa: BLE001 - telemetry must never take the server down
                pass
        return s

    def close(self):
        """Ends the sampler thread (a server that stops, a test's service): it used to run for the life of the process."""
        self._stop.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _loop(self):
        while not getattr(self, "_stop", threading.Event()).is_set():
            try:
                s = self.sample()
            except Exception:  # A broken sensor must not permanently stop monitoring.
                s = {"time": time.time(), "sample_error": True}
            with self.lock:
                self.now = s
                if self.static.get("gpu_vram_total_mib") is None and s.get("gpu_mem_total"):
                    self.static["gpu_vram_total_mib"] = int(s["gpu_mem_total"] >> 20)
                try:                     # a missing/broken efficiency module must not end the sampler
                    from serve.efficiency import capture
                    measured = capture(s, time.time())
                    if measured is not None:
                        self.last_efficiency = measured
                except Exception:
                    pass
                for k in ("gpu_util", "gpu_mem_used", "gpu_temp", "gpu_temp_hotspot", "gpu_vram_temp", "gpu_power",
                          "gpu_volt", "cpu_temp", "cpu_temp_avg", "cpu_power", "pch_temp", "nvme_temp",
                          "gpu_pcie_rx_mb", "cpu", "ram_used", "disk_read_mb", "tok_s",
                          "prefill_tok_s_mean", "eff"):
                    v = s.get(k)
                    self.hist[k].append(round(v, 2) if isinstance(v, float) else v)
            if getattr(self, "_stop", None) is not None:
                self._stop.wait(1.0)
            else:
                time.sleep(1.0)

    def snapshot(self):
        with self.lock:
            return {"now": dict(self.now), "history": {k: list(v) for k, v in self.hist.items()},
                    "static": dict(self.static),
                    "efficiency_sample": dict(self.last_efficiency) if self.last_efficiency else None}
