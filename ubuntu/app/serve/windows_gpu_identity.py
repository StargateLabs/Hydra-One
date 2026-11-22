"""DXGI adapter identity only: no kernels, GPU allocations or driver changes."""
import ctypes
import os
import uuid

def amd_luid(index=0):
    if os.name != 'nt':
        return None
    class Luid(ctypes.Structure):
        _fields_ = [('LowPart',ctypes.c_uint32),('HighPart',ctypes.c_int32)]
    class Desc(ctypes.Structure):
        _fields_ = [('Description',ctypes.c_wchar*128),('VendorId',ctypes.c_uint32),
                    ('DeviceId',ctypes.c_uint32),('SubSysId',ctypes.c_uint32),('Revision',ctypes.c_uint32),
                    ('DedicatedVideoMemory',ctypes.c_size_t),('DedicatedSystemMemory',ctypes.c_size_t),
                    ('SharedSystemMemory',ctypes.c_size_t),('AdapterLuid',Luid),('Flags',ctypes.c_uint32)]
    def method(pointer, slot, *args):
        table=ctypes.cast(pointer,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(ctypes.c_long,ctypes.c_void_p,*args)(table[slot])
    factory=ctypes.c_void_p()
    try:
        iid=(ctypes.c_ubyte*16).from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
        dxgi=ctypes.WinDLL('dxgi')
        dxgi.CreateDXGIFactory1.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid),ctypes.byref(factory)) != 0:
            return None
        found=0
        for ordinal in range(32):
            adapter=ctypes.c_void_p()
            if method(factory,12,ctypes.c_uint32,ctypes.POINTER(ctypes.c_void_p))(factory,ordinal,ctypes.byref(adapter)) != 0:
                break
            try:
                desc=Desc()
                if method(adapter,10,ctypes.POINTER(Desc))(adapter,ctypes.byref(desc)) == 0 and desc.VendorId == 0x1002:
                    if found == index:
                        return f'luid_0x{desc.AdapterLuid.HighPart & 0xffffffff:08x}_0x{desc.AdapterLuid.LowPart:08x}'
                    found+=1
            finally:
                method(adapter,2)(adapter)
    except (OSError, ValueError, AttributeError):
        return None
    finally:
        if factory.value:
            method(factory,2)(factory)
    return None

def adapter_values(values, luid):
    return {name:value for name,value in values.items() if luid and luid.lower() in name.lower()}
