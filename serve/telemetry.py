"""serve/telemetry.py - hardware readings for the web app's Monitor tab (idea from PR #22 by code-martin).

A background thread samples once a second and keeps the last 60 readings of each series for the sparklines:
- GPU: NVIDIA's own NVML library (nvml.dll / libnvidia-ml.so.1, installed with every driver) through ctypes, so no
  pip package is needed: load, VRAM, temperature, power, PCIe link and throughput.  With the AMD backend (#301): the
  amdgpu driver's Linux sysfs files - load, VRAM, temperature and power.
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
try:
    import wmi   # type: ignore
except Exception:  # pragma: no cover
    wmi = None   # type: ignore

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
        return out


# ------------------------------------------------------------------------------------------------ AMD (Windows PDH)
class _AmdWindows:
    """#301 on Windows: an AMD card's readings through the OS GPU performance counters, read with PDH (the API
    Task Manager uses - a query is microseconds, WMI's was 5-7 SECONDS a read and stole CPU from the expert
    pool): GPU load (GPU Engine counters, summed over every process × engine), VRAM (GPU Adapter Memory
    dedicated), Total Committed.  Temperature and power are NOT in the OS counters for AMD; when AIDA64 runs
    with its shared memory on they come from there (its 4 KB XML page), otherwise they stay None.  Nothing here
    can stop the server: every read is guarded."""

    def __init__(self, index=0):
        self._ok = False
        self._amd_index = index
        self._pdh = self._q_util = self._q_mem = self._q_tc = None
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
            self._ok = bool(self._h_util and self._h_mem)
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
        The page is a fixed 4 KB whose last block is cut off, so the parse must not depend on closing tags."""
        if self._k32 is None:
            return None
        try:
            h = self._k32.OpenFileMappingW(0x0004, False, "AIDA64_SensorValues")
            if not h:
                return None
            p = self._k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
            if not p:
                self._k32.CloseHandle(h)
                return None
            try:
                raw = ctypes.string_at(p, 4096)   # one 4 KB page; reading past it faults
            except OSError:
                raw = b""
            self._k32.UnmapViewOfFile(p)
            self._k32.CloseHandle(h)
            text = raw.decode("utf-8", "replace")
            return {sid: value.strip() for sid, _label, value in
                    re.findall(r"<id>([^<]+)</id><label>([^<]*)</label><value>([^<]*)</value>", text)} or None
        except Exception:
            return None

    def ok(self):
        return self._ok

    def name(self):
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
        util = adapter_values(self._array(self._h_util[0]), self._adapter_luid) if self._h_util else {}
        if util:
            out["util"] = min(100.0, sum(util.values()))

        # ---- VRAM: DedicatedUsage (bytes on the card) per adapter, the luid_…_phys_0 instance without a pid_
        # prefix is the adapter's own; the card's size comes from the driver's registry entry.
        mem = adapter_values(self._array(self._h_mem[0]), self._adapter_luid) if self._h_mem else {}
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
    """The card's readings: NVML (NVIDIA), or the amdgpu sysfs files with the AMD backend (#301)."""
    if amd:
        # On Windows the sysfs reader cannot work: use the OS GPU counters instead
        if os.name == "nt":
            return _AmdWindows(index)
        return _Amd(index)
    return _Nvml(index)


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
        self.last_efficiency = None
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
        self.static = {
            "gpu_name": " + ".join(g.name() or "?" for _, g in self.gpus) if self.gpu.ok() else None,
            "gpu_count": len(self.gpus),
            "cpu_name": _cpu_name(),
            "cores": (self.ps.cpu_count(logical=False) if self.ps else None) or None,
            "threads": os.cpu_count(),
            "psutil": self.ps is not None,
        }
        if amd:
            # Query the installed HIP runtime; never infer an architecture from a product name.
            try:
                import setup as strata_setup
                probe = strata_setup.ROOT / "engine" / ("strata-device.exe" if os.name == "nt" else "strata-device")
                env = dict(os.environ)
                env["PATH"] = os.pathsep.join([str(d) for d in strata_setup.hip_lib_dirs(probe.parent)] + [env.get("PATH", "")])
                result = subprocess.run([str(probe), "--list-devices"], capture_output=True,
                                        text=True, timeout=8, cwd=str(probe.parent), env=env,
                                        creationflags=0x08000000 if os.name == "nt" else 0)
                devices = strata_setup.hip_devices(text=result.stdout) if result.returncode == 0 else []
                self.static["gpu_archs"] = [g["arch"] for g in (devices or [])
                                           if g["index"] in idx and re.fullmatch(r"gfx[0-9a-f]+", g["arch"])]
            except (OSError, ValueError, RuntimeError, ImportError, AttributeError, subprocess.TimeoutExpired):
                self.static["gpu_archs"] = []
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
                s["gpus"] = [{"index": i, "util": r.get("util"), "mem_used": r.get("mem_used"),
                              "mem_total": r.get("mem_total"), "temp": r.get("temp"), "power": r.get("power")}
                             for i, r in reads]
            s.update({f"gpu_{k}": v for k, v in g.items()})
            # the AMD reader also reads the CPU package sensors AIDA64 shares (they power the expert pool):
            # the gpu_ prefix above would hide them as gpu_cpu_temp / gpu_cpu_power, so expose them plainly too.
            for k in ("cpu_temp", "cpu_power"):
                if g.get(k) is not None:
                    s[k] = g[k]
        if self.ps:
            try:
                s["cpu"] = self.ps.cpu_percent(interval=None)
                vm = self.ps.virtual_memory()
                s["ram_used"], s["ram_total"] = vm.total - vm.available, vm.total
            except (OSError, RuntimeError, AttributeError, TypeError, ValueError):
                pass
        else:
            s["cpu"] = self.fallback.cpu()
            s["ram_used"], s["ram_total"] = self.fallback.ram()
        s["disk_read_mb"], s["disk_write_mb"] = self._disk()
        if self.extra:
            try:
                s.update(self.extra())
            except Exception:  # noqa: BLE001 - telemetry must never take the server down
                pass
        # efficiency: tokens per second per watt (0 when no power or no speed)
        power = s.get("gpu_power") or 0.0
        tok_s = s.get("tok_s") or 0.0
        s["eff"] = round(tok_s / power, 2) if power > 0 and tok_s > 0 else 0.0
        return s

    def close(self):
        """Stop the sampler owned by this server; retain its last snapshot."""
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
                from serve.efficiency import capture
                measured = capture(s, time.time())
                if measured is not None:
                    self.last_efficiency = measured
                for k in ("gpu_util", "gpu_mem_used", "gpu_temp", "gpu_temp_hotspot", "gpu_vram_temp", "gpu_power",
                          "gpu_volt", "cpu_temp", "cpu_power", "gpu_pcie_rx_mb", "cpu", "ram_used", "disk_read_mb", "tok_s",
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
