"""Read-only HIP capability query. No streams, allocations or wait kernels."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import time
ROOT=Path(__file__).resolve().parents[1]

def main():
    import sys
    sys.path.insert(0,str(ROOT))
    from serve.gpu_lease import GpuLease
    import urllib.request
    with GpuLease(ROOT,'hip-capability-readonly'):
        metrics=json.load(urllib.request.urlopen('http://127.0.0.1:8088/metrics'))
        if metrics['live']['state']!='unloaded':raise RuntimeError('Operational model must be unloaded')
        header=ROOT/'.rocm-win/Lib/site-packages/_rocm_sdk_devel/include/hip/hip_runtime_api.h'
        text=header.read_text();start=text.index('hipDeviceAttributeClockInstructionRate =');end=text.index('hipDeviceAttributeCanUseStreamWaitValue',start)
        names=re.findall(r'\b(hipDeviceAttribute\w+)\s*(?:=|,)',text[start:end])
        names=[n for n in names if n!='hipDeviceAttributeAmdSpecificBegin']
        attribute=10000+len(names)
        if attribute!=10013:raise RuntimeError('Unexpected HIP enum; do not guess numeric capability')
        runtime=ROOT/'engine/amdhip64_7.dll'
        handle=os.add_dll_directory(str(runtime.parent))
        lib=ctypes.WinDLL(str(runtime));lib.hipInit.argtypes=[ctypes.c_uint];lib.hipInit.restype=ctypes.c_int
        lib.hipDeviceGetAttribute.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_int,ctypes.c_int];lib.hipDeviceGetAttribute.restype=ctypes.c_int
        init=lib.hipInit(0);value=ctypes.c_int(-1);code=lib.hipDeviceGetAttribute(ctypes.byref(value),attribute,0) if init==0 else init
        result=dict(checked_at=time.time(),hip_init_return=init,attribute=attribute,attribute_name='hipDeviceAttributeCanUseStreamWaitValue',query_return=code,
            supported=bool(value.value) if code==0 else None,raw_value=value.value,hip_dll_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),
            header=str(header.relative_to(ROOT)),scope='Capability query only; no wait/write calls, no allocation, no graph-capture support claim')
        target=ROOT/'output/verification/hip-stream-wait-capability.json';target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));handle.close()

if __name__=='__main__':main()
