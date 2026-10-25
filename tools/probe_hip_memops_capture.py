"""Small, owned HIP probe. All waits are satisfied before capture or launch.

Never enqueue an unsatisfied GPU wait. No model, no compute kernels, no driver changes.
"""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET=ROOT/'output/verification/hip-memops-capture.json'
def child():
    directory=os.add_dll_directory(str(ROOT/'engine'));hip=C.WinDLL(str(ROOT/'engine/amdhip64_7.dll'))
    def function(name,types):
        fn=getattr(hip,name);fn.argtypes=types;fn.restype=C.c_int;return fn
    init=function('hipInit',[C.c_uint]);malloc=function('hipHostMalloc',[C.POINTER(C.c_void_p),C.c_size_t,C.c_uint]);alias=function('hipHostGetDevicePointer',[C.POINTER(C.c_void_p),C.c_void_p,C.c_uint])
    free=function('hipHostFree',[C.c_void_p]);create=function('hipStreamCreateWithFlags',[C.POINTER(C.c_void_p),C.c_uint]);sync=function('hipStreamSynchronize',[C.c_void_p]);destroy=function('hipStreamDestroy',[C.c_void_p])
    write=function('hipStreamWriteValue32',[C.c_void_p,C.c_void_p,C.c_uint32,C.c_uint]);wait=function('hipStreamWaitValue32',[C.c_void_p,C.c_void_p,C.c_uint32,C.c_uint,C.c_uint32])
    begin=function('hipStreamBeginCapture',[C.c_void_p,C.c_int]);end=function('hipStreamEndCapture',[C.c_void_p,C.POINTER(C.c_void_p)]);nodes=function('hipGraphGetNodes',[C.c_void_p,C.c_void_p,C.POINTER(C.c_size_t)])
    instantiate=function('hipGraphInstantiateWithFlags',[C.POINTER(C.c_void_p),C.c_void_p,C.c_uint64]);launch=function('hipGraphLaunch',[C.c_void_p,C.c_void_p]);graphfree=function('hipGraphDestroy',[C.c_void_p]);execfree=function('hipGraphExecDestroy',[C.c_void_p])
    result=dict(status='running',started_at=time.time(),calls=[],scope='Mapped coherent flags; waits already satisfied; no asynchronous CPU publication or model validation')
    host=C.c_void_p();device=C.c_void_p();stream=C.c_void_p();graph=C.c_void_p();exe=C.c_void_p();capturing=False
    def check(name,code):
        result['calls'].append(dict(operation=name,returncode=code));TARGET.write_text(json.dumps(result,indent=2)+'\n')
        if code:raise RuntimeError(f'{name}: HIP return {code}')
    try:
        check('hipInit',init(0));check('mapped coherent host allocation',malloc(C.byref(host),64,0x2|0x40000000));check('mapped device alias',alias(C.byref(device),host,0));check('nonblocking stream',create(C.byref(stream),1))
        ready=device;out=C.c_void_p(device.value+8);ready_host=C.c_uint32.from_address(host.value);out_host=C.c_uint32.from_address(host.value+8)
        check('write ready=16',write(stream,ready,16,0));check('write output=0',write(stream,out,0,0));check('initial sync',sync(stream))
        if ready_host.value!=16:raise RuntimeError('GPU publication not visible; no wait enqueued')
        check('begin capture',begin(stream,1));capturing=True
        check('capture satisfied wait >=1',wait(stream,ready,1,0,0xffffffff));check('capture write output=77',write(stream,out,77,0))
        code=end(stream,C.byref(graph));capturing=False;check('end capture',code)
        count=C.c_size_t();check('graph node count',nodes(graph,None,C.byref(count)));result['captured_nodes']=count.value
        if count.value<2:raise RuntimeError('Wait and write were not both captured')
        check('instantiate',instantiate(C.byref(exe),graph,0));result['replays']=[]
        for index in range(8):
            check('reset output',write(stream,out,0,0));check('reset sync',sync(stream))
            if ready_host.value!=16 or out_host.value!=0:raise RuntimeError('Precondition not satisfied; no graph launched')
            check('graph launch',launch(exe,stream));check('graph sync',sync(stream))
            result['last_observation']=dict(index=index,ready=ready_host.value,output=out_host.value,expected_ready=16,expected_output=77)
            if ready_host.value!=16 or out_host.value!=77:raise RuntimeError('Captured write did not replay correctly')
            result['replays'].append(dict(index=index,ready=ready_host.value,output=out_host.value))
        result.update(status='complete',supported_for_satisfied_mapped_graph=True)
    except Exception as exc:result.update(status='rejected',error=str(exc),supported_for_satisfied_mapped_graph=False)
    finally:
        if capturing:end(stream,C.byref(graph))
        if exe.value:execfree(exe)
        if graph.value:graphfree(graph)
        if stream.value:destroy(stream)
        if host.value:free(host)
        result['finished_at']=time.time();TARGET.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));directory.close()
def main():
    from serve.gpu_lease import GpuLease
    import socket
    import urllib.request
    with GpuLease(ROOT,'hip-memops-capture-probe'):
        if json.load(urllib.request.urlopen('http://127.0.0.1:8088/metrics'))['live']['state']!='unloaded':raise RuntimeError('Operational model must be unloaded')
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8089))==0:raise RuntimeError('Isolated server active')
        try:
            run=subprocess.run([sys.executable,__file__,'--child'],cwd=ROOT,capture_output=True,text=True,timeout=30)
            if run.returncode:raise RuntimeError(f'Owned probe failed: {run.returncode}; {run.stderr[-400:]}')
            print(run.stdout)
        except subprocess.TimeoutExpired:
            TARGET.write_text(json.dumps(dict(status='timeout',supported_for_satisfied_mapped_graph=False,scope='No unsatisfied waits were intentionally queued'),indent=2)+'\n');raise
if __name__=='__main__':child() if '--child' in sys.argv else main()
