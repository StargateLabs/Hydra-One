"""NVIDIA VRAM observer for HYDRA on Linux. NVML only; never resets or owns the GPU."""
import ctypes
import os
import time


class NvidiaUnavailable(RuntimeError):
    pass


class _Memory(ctypes.Structure):
    _fields_=[('total',ctypes.c_ulonglong),('free',ctypes.c_ulonglong),('used',ctypes.c_ulonglong)]


def _library():
    names=('libnvidia-ml.so.1','libnvidia-ml.so','nvml.dll')
    errors=[]
    for name in names:
        try:return ctypes.CDLL(name)
        except OSError as exc:errors.append(str(exc))
    raise NvidiaUnavailable('NVIDIA NVML not available: '+'; '.join(errors))


class NvidiaObserver:
    def __init__(self,index=None):
        from hydra_hybrid.config import Resources,host_resources
        self._Resources=Resources;self._host_resources=host_resources
        self.api=_library()
        for name,args,restype in (
            ('nvmlInit_v2',[],ctypes.c_int),
            ('nvmlDeviceGetCount_v2',[ctypes.POINTER(ctypes.c_uint)],ctypes.c_int),
            ('nvmlDeviceGetHandleByIndex_v2',[ctypes.c_uint,ctypes.POINTER(ctypes.c_void_p)],ctypes.c_int),
            ('nvmlDeviceGetMemoryInfo',[ctypes.c_void_p,ctypes.POINTER(_Memory)],ctypes.c_int),
            ('nvmlDeviceGetName',[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_uint],ctypes.c_int),
        ):
            function=getattr(self.api,name);function.argtypes=args;function.restype=restype
        self._check('nvmlInit_v2',self.api.nvmlInit_v2())
        count=ctypes.c_uint();self._check('nvmlDeviceGetCount_v2',self.api.nvmlDeviceGetCount_v2(ctypes.byref(count)))
        if not count.value:raise NvidiaUnavailable('NVIDIA NVML reports no devices')
        if index is None:index=int(os.environ.get('STRATA_NVIDIA_GPU','0') or 0)
        if not 0<=index<count.value:raise NvidiaUnavailable('NVIDIA GPU index outside 0..'+str(count.value-1))
        self.index=index;self.handle=ctypes.c_void_p()
        self._check('nvmlDeviceGetHandleByIndex_v2',self.api.nvmlDeviceGetHandleByIndex_v2(index,ctypes.byref(self.handle)))
        buffer=ctypes.create_string_buffer(96)
        self.name='NVIDIA GPU '+str(index)
        try:
            if self.api.nvmlDeviceGetName(self.handle,buffer,len(buffer))==0:
                self.name=buffer.value.decode('utf-8','replace')
        except Exception:
            pass
        self.closed=False

    def _check(self,name,code):
        if code:raise NvidiaUnavailable(name+' failed with NVML code '+str(code))

    def sample(self):
        memory=_Memory()
        self._check('nvmlDeviceGetMemoryInfo',self.api.nvmlDeviceGetMemoryInfo(self.handle,ctypes.byref(memory)))
        host=self._host_resources()
        return self._Resources(host_available_bytes=host.host_available_bytes,vram_available_bytes=int(memory.free)),dict(
            source='NVML nvmlDeviceGetMemoryInfo; current selected device',device=self.index,name=self.name,
            free_bytes=int(memory.free),total_allocatable_bytes=int(memory.total),monotonic_ns=time.monotonic_ns())

    def close(self):
        # NVML shutdown is process-global; leaving it alone keeps other local monitors valid.
        self.closed=True
