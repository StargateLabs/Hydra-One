"""Owned copy-only HIP probe using host time, never Windows HIP event timings.

No model, graphs, kernels, unsatisfied waits, or system changes. The caller reserves
the GPU and requires the operational engine to be unloaded before a bounded child.
"""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET=ROOT/'output/verification/hip-wall-bandwidth.json'
MAX_BYTES=256<<20

def child():
    directory=os.add_dll_directory(str(ROOT/'engine'))
    hip=C.WinDLL(str(ROOT/'engine/amdhip64_7.dll'))
    def fn(name,types):
        f=getattr(hip,name);f.argtypes=types;f.restype=C.c_int;return f
    init=fn('hipInit',[C.c_uint])
    malloc=fn('hipMalloc',[C.POINTER(C.c_void_p),C.c_size_t]);free=fn('hipFree',[C.c_void_p])
    hostmalloc=fn('hipHostMalloc',[C.POINTER(C.c_void_p),C.c_size_t,C.c_uint]);hostfree=fn('hipHostFree',[C.c_void_p])
    register=fn('hipHostRegister',[C.c_void_p,C.c_size_t,C.c_uint]);unregister=fn('hipHostUnregister',[C.c_void_p])
    copy=fn('hipMemcpyAsync',[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int,C.c_void_p])
    copy_sync=fn('hipMemcpy',[C.c_void_p,C.c_void_p,C.c_size_t,C.c_int])
    synchronize=fn('hipStreamSynchronize',[C.c_void_p])
    create=fn('hipStreamCreateWithFlags',[C.POINTER(C.c_void_p),C.c_uint]);destroy=fn('hipStreamDestroy',[C.c_void_p])
    memory=fn('hipMemGetInfo',[C.POINTER(C.c_size_t),C.POINTER(C.c_size_t)])
    version=fn('hipRuntimeGetVersion',[C.POINTER(C.c_int)])
    result={'status':'running','started_at':time.time(),'scope':'Copy-only host-wall timings; not physical-link diagnosis or model throughput',
            'max_device_bytes':MAX_BYTES,'rows':[],'calls_failed':[],'allocation_modes':[]}
    def save():TARGET.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    def check(name,code):
        if code:
            result['calls_failed'].append({'operation':name,'returncode':code});save()
            raise RuntimeError(f'{name}: HIP {code}')
    dev=C.c_void_p();stream=C.c_void_p();host=C.c_void_p();registered=False;owner=None
    try:
        check('hipInit',init(0));v=C.c_int();check('runtime version',version(C.byref(v)));result['runtime_version']=v.value
        available=C.c_size_t();total=C.c_size_t();check('memory info',memory(C.byref(available),C.byref(total)))
        result['initial_free_bytes']=available.value
        if available.value<MAX_BYTES+(1536<<20):raise RuntimeError('Insufficient initial VRAM margin')
        check('device allocation',malloc(C.byref(dev),MAX_BYTES));check('stream',create(C.byref(stream),1))
        for mode in ('pageable','pinned_default','pinned_write_combined','registered_default'):
            host=C.c_void_p();owner=None;registered=False
            try:
                if mode in ('pageable','registered_default'):
                    owner=C.create_string_buffer(MAX_BYTES+4096);host=C.c_void_p((C.addressof(owner)+4095)&~4095)
                    if mode=='registered_default':check('register host',register(host,MAX_BYTES,0));registered=True
                else:check('host allocation '+mode,hostmalloc(C.byref(host),MAX_BYTES,4 if mode=='pinned_write_combined' else 0))
                C.memset(host,0x5a,MAX_BYTES)
                result['allocation_modes'].append(mode)
                # Reading this memory is relevant to CPU expert kernels; WC can harm
                # that path even if upload throughput improves. Small read only.
                scratch=C.create_string_buffer(1<<20);reads=[]
                for _ in range(3):
                    t=time.perf_counter();C.memmove(scratch,host,1<<20);reads.append(time.perf_counter()-t)
                result.setdefault('host_read_copy',{})[mode]={'bytes':1<<20,'median_gbps':(1<<20)/statistics.median(reads)/1e9}
                for stream_name,st in (('default',C.c_void_p()),('nonblocking',stream)):
                    for size in (1<<20,16<<20,64<<20,MAX_BYTES):
                        for _ in range(2):check('warmup copy',copy(dev,host,size,1,st));check('warmup sync',synchronize(st))
                        milliseconds=[]
                        for _ in range(7):
                            check('before timing sync',synchronize(st));t=time.perf_counter()
                            check('timed copy',copy(dev,host,size,1,st));check('timed sync',synchronize(st))
                            milliseconds.append((time.perf_counter()-t)*1000)
                        # Verify both ends, outside timing; no assumed-success copies.
                        for offset in (0,size-32):
                            back=C.create_string_buffer(32)
                            check('verify copy back',copy_sync(back,C.c_void_p(dev.value+offset),32,2))
                            if back.raw!=bytes([0x5a])*32:raise RuntimeError('Copy payload verification failed')
                        speeds=[size/(ms/1000)/1e9 for ms in milliseconds]
                        result['rows'].append({'mode':mode,'stream':stream_name,'bytes':size,'samples_ms':milliseconds,
                            'median_gbps':statistics.median(speeds),'best_gbps':max(speeds),'verified':True})
                        save()
            finally:
                if registered:check('unregister host',unregister(host));registered=False
                elif host.value and mode.startswith('pinned'):check('free host',hostfree(host))
                host=C.c_void_p();owner=None
        result['status']='complete'
    except Exception as exc:result.update(status='failed',error=str(exc))
    finally:
        if stream.value:destroy(stream)
        if dev.value:free(dev)
        result['finished_at']=time.time();save();directory.close()
    print(json.dumps({'status':result['status'],'rows':len(result['rows']),'error':result.get('error')}))
    if result['status']!='complete':raise SystemExit(1)

def main():
    from serve.gpu_lease import GpuLease
    with GpuLease(ROOT,'hip-wall-bandwidth'):
        metrics=json.load(urllib.request.urlopen('http://127.0.0.1:8088/metrics',timeout=5))
        if metrics['live']['state']!='unloaded' or metrics['live'].get('queued'):raise RuntimeError('Operational engine must be unloaded and idle')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8089))==0:raise RuntimeError('Isolated server active')
        try:
            completed=subprocess.run([sys.executable,__file__,'--child'],cwd=ROOT,capture_output=True,text=True,timeout=60)
            (TARGET.with_suffix('.log')).write_text(completed.stdout+completed.stderr,encoding='utf-8')
            if completed.returncode:raise RuntimeError('Copy-only probe failed; inspect hip-wall-bandwidth.json/.log')
        except subprocess.TimeoutExpired:
            raise RuntimeError('Owned copy-only probe timed out; no model was loaded') from None
        d=json.loads(TARGET.read_text(encoding='utf-8'));d['hardware']=metrics.get('hardware_static',{});d['hip_dll_sha256']=hashlib.sha256((ROOT/'engine/amdhip64_7.dll').read_bytes()).hexdigest();d['probe_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        TARGET.write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
        print(completed.stdout.strip())
        for row in d['rows']:
            if row['bytes']==MAX_BYTES:print(row['mode'],row['stream'],round(row['median_gbps'],2),'GB/s')

if __name__=='__main__':child() if '--child' in sys.argv else main()
