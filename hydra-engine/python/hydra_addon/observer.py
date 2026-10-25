"""Opt-in RX7900XTX HIP observer reused from the verified local harness."""
import os,ctypes,time
from hydra_hybrid.config import Resources,host_resources

class HIPObserver:
    """Existing HIP C runtime; free/total from hipMemGetInfo, not board capacity."""
    def __init__(self, directory):
        self.dll_directory=os.add_dll_directory(str(directory))
        self.api=ctypes.CDLL(str(directory/'amdhip64_7.dll'))
        for name,args in (
            ('hipInit',[ctypes.c_uint]),
            ('hipGetDeviceCount',[ctypes.POINTER(ctypes.c_int)]),
            ('hipSetDevice',[ctypes.c_int]),
            ('hipMemGetInfo',[ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]),
            ('hipDeviceGetName',[ctypes.POINTER(ctypes.c_char),ctypes.c_int,ctypes.c_int])):
            function=getattr(self.api,name);function.argtypes=args;function.restype=ctypes.c_int
        self.check('hipInit',0)
        count=ctypes.c_int();self.check('hipGetDeviceCount',ctypes.byref(count))
        self.device=None;self.name=None
        for device in range(count.value):
            name=ctypes.create_string_buffer(256)
            self.check('hipDeviceGetName',name,256,device)
            label=name.value.decode(errors='replace')
            if '7900 XTX' in label:
                self.device=device;self.name=label;break
        if self.device is None:raise RuntimeError('Approved RX 7900 XTX not observed; no GPU inference')

    def check(self,name,*args):
        code=getattr(self.api,name)(*args)
        if code:raise RuntimeError(name+' failed with HIP code '+str(code))

    def sample(self):
        self.check('hipSetDevice',self.device)
        free=ctypes.c_size_t();total=ctypes.c_size_t()
        self.check('hipMemGetInfo',ctypes.byref(free),ctypes.byref(total))
        host=host_resources()
        return Resources(host_available_bytes=host.host_available_bytes,vram_available_bytes=free.value),dict(
            source='HIP hipMemGetInfo; current selected device',device=self.device,name=self.name,
            free_bytes=free.value,total_allocatable_bytes=total.value,monotonic_ns=time.monotonic_ns())

    def close(self):
        self.dll_directory.close()
        # No global hipDeviceReset: never reset a shared physical GPU.

