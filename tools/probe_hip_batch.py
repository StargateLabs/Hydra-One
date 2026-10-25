"""Bounded, copy-only test of HIP batch uploads omitted by Strata's HIP path."""
import ctypes as C
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET=ROOT/'output/verification/hip-batch-copies.json'

def child():
    directory=os.add_dll_directory(str(ROOT/'engine'));hip=C.WinDLL(str(ROOT/'engine/amdhip64_7.dll'))
    report={'status':'running','scope':'Synthetic independent blob copies; no model','rows':[]}
    def save():TARGET.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    def fn(name,types):f=getattr(hip,name);f.argtypes=types;f.restype=C.c_int;return f
    def check(name,code):
        if code:raise RuntimeError(f'{name}: HIP {code}')
    host=C.c_void_p();dev=C.c_void_p();stream=C.c_void_p()
    try:
        batch=fn('hipMemcpyBatchAsync',[C.POINTER(C.c_void_p),C.POINTER(C.c_void_p),C.POINTER(C.c_size_t),C.c_size_t,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t),C.c_void_p])
        malloc=fn('hipMalloc',[C.POINTER(C.c_void_p),C.c_size_t]);free=fn('hipFree',[C.c_void_p])
        hostmalloc=fn('hipHostMalloc',[C.POINTER(C.c_void_p),C.c_size_t,C.c_uint]);hostfree=fn('hipHostFree',[C.c_void_p])
        alias=fn('hipHostGetDevicePointer',[C.POINTER(C.c_void_p),C.c_void_p,C.c_uint])
        create=fn('hipStreamCreateWithFlags',[C.POINTER(C.c_void_p),C.c_uint]);destroy=fn('hipStreamDestroy',[C.c_void_p]);sync=fn('hipStreamSynchronize',[C.c_void_p])
        copy=fn('hipMemcpyAsync',[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int,C.c_void_p]);backcopy=fn('hipMemcpy',[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int])
        memory=fn('hipMemGetInfo',[C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)])
        available=C.c_size_t();total=C.c_size_t();check('memory info',memory(C.byref(available),C.byref(total)))
        if available.value< (1536+32)<<20:raise RuntimeError('Insufficient VRAM margin')
        check('allocate device',malloc(C.byref(dev),16<<20));check('allocate host',hostmalloc(C.byref(host),16<<20,2))
        visible=C.c_void_p();check('host alias',alias(C.byref(visible),host,0));check('stream',create(C.byref(stream),1))
        for blob_bytes in (64<<10,1<<20):
            for count in (4,16):
                for i in range(count):C.memset(C.c_void_p(host.value+i*blob_bytes),i+1,blob_bytes)
                destinations=(C.c_void_p*count)(*[dev.value+i*blob_bytes for i in range(count)])
                sources=(C.c_void_p*count)(*[visible.value+(count-1-i)*blob_bytes for i in range(count)])
                sizes=(C.c_size_t*count)(*[blob_bytes]*count)
                expected=b''.join(bytes([count-i])*blob_bytes for i in range(count))
                for mode in ('loop','batch'):
                    samples=[]
                    for run in range(9):
                        check('before sync',sync(stream));t=time.perf_counter()
                        if mode=='loop':
                            for i in range(count):check('copy',copy(C.c_void_p(destinations[i]),C.c_void_p(host.value+(count-1-i)*blob_bytes),blob_bytes,1,stream))
                        else:
                            failure=C.c_size_t(-1);check('batch',batch(destinations,sources,sizes,count,None,None,0,C.byref(failure),stream))
                        check('after sync',sync(stream));elapsed=(time.perf_counter()-t)*1000
                        if run>=2:samples.append(elapsed)
                    out=C.create_string_buffer(count*blob_bytes);check('verify download',backcopy(out,dev,count*blob_bytes,2))
                    if out.raw!=expected:raise RuntimeError('Batch upload payload mismatch')
                    report['rows'].append({'mode':mode,'blob_bytes':blob_bytes,'count':count,'median_ms':statistics.median(samples),'samples_ms':samples,'verified_bytes':len(expected)});save()
        report.update(status='complete',supported=True)
    except Exception as exc:report.update(status='rejected',supported=False,error=str(exc))
    finally:
        if stream.value:destroy(stream)
        if dev.value:free(dev)
        if host.value:hostfree(host)
        save();directory.close()
    print(json.dumps(report))

def main():
    from serve.gpu_lease import GpuLease
    with GpuLease(ROOT,'hip-batch-probe'):
        metrics=json.load(urllib.request.urlopen('http://127.0.0.1:8088/metrics',timeout=5))
        if metrics['live']['state']!='unloaded' or metrics['live'].get('queued'):raise RuntimeError('Operational model must be unloaded')
        run=subprocess.run([sys.executable,__file__,'--child'],cwd=ROOT,capture_output=True,text=True,timeout=30)
        TARGET.with_suffix('.log').write_text(run.stdout+run.stderr,encoding='utf-8')
        if run.returncode:raise RuntimeError('Owned batch probe failed')
        result=json.loads(TARGET.read_text());print(result['status'],result.get('error',''))
        for row in result['rows']:print(row['mode'],row['blob_bytes'],row['count'],round(row['median_ms'],3),'ms')
if __name__=='__main__':child() if '--child' in sys.argv else main()
