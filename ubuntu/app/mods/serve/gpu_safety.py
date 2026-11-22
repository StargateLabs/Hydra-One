"""Headroom limits for GPU validation runs. This module never touches the GPU."""
import ctypes
import math
import os

MIN_RAM_FREE_GIB = 20.0
MIN_COMMIT_FREE_GIB = 12.0
ABORT_COMMIT_FREE_GIB = 6.0


def commit_available_gib():
    """Windows commit headroom (RAM + page file), or None where the platform has no such limit."""
    if os.name != 'nt':
        return None
    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0.0
    except (AttributeError, OSError):
        return 0.0
    return status.ullAvailPageFile / 2 ** 30


def preflight_refusal(ram_free_gib, commit_free_gib=None):
    """Why a validation run must not start, or None when the headroom is acceptable."""
    if ram_free_gib < MIN_RAM_FREE_GIB:
        return (f'Free RAM is {ram_free_gib:.1f} GiB; at least {MIN_RAM_FREE_GIB:.0f} GiB is required '
                'before a GPU validation run')
    if commit_free_gib is not None and math.isfinite(commit_free_gib) and commit_free_gib < MIN_COMMIT_FREE_GIB:
        return (f'Windows commit headroom is {commit_free_gib:.1f} GiB; at least {MIN_COMMIT_FREE_GIB:.0f} GiB '
                'is required. Raise the page file (System managed) or lower the profile before a GPU run')
    return None
