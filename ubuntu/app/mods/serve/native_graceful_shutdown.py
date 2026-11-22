"""Ask Windows to release one owned app without the force-shutdown flag."""
import ctypes,os
from ctypes import wintypes

class UniqueProcess(ctypes.Structure):
    _fields_=[('pid',wintypes.DWORD),('started',wintypes.FILETIME)]

def shutdown(pid):
    if os.name!='nt':raise RuntimeError('Windows native shutdown only')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);manager=ctypes.WinDLL('rstrtmgr',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*[ctypes.POINTER(wintypes.FILETIME)]*4];kernel.GetProcessTimes.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    manager.RmStartSession.argtypes=[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,wintypes.LPWSTR];manager.RmStartSession.restype=wintypes.DWORD
    manager.RmRegisterResources.argtypes=[wintypes.DWORD,wintypes.UINT,ctypes.c_void_p,wintypes.UINT,ctypes.POINTER(UniqueProcess),wintypes.UINT,ctypes.c_void_p];manager.RmRegisterResources.restype=wintypes.DWORD
    manager.RmShutdown.argtypes=[wintypes.DWORD,wintypes.ULONG,ctypes.c_void_p];manager.RmShutdown.restype=wintypes.DWORD
    manager.RmEndSession.argtypes=[wintypes.DWORD];manager.RmEndSession.restype=wintypes.DWORD
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle:return {'stopped':True,'already_closed':True}
    started,ended,kernel_time,user_time=[wintypes.FILETIME() for _ in range(4)]
    try:
        if not kernel.GetProcessTimes(handle,ctypes.byref(started),ctypes.byref(ended),ctypes.byref(kernel_time),ctypes.byref(user_time)):
            raise OSError(ctypes.get_last_error(),'Cannot verify native process creation time')
    finally:kernel.CloseHandle(handle)
    session=wintypes.DWORD();key=ctypes.create_unicode_buffer(33)
    code=manager.RmStartSession(ctypes.byref(session),0,key)
    if code:raise OSError(code,'Cannot start graceful app shutdown session')
    try:
        process=UniqueProcess(int(pid),started)
        code=manager.RmRegisterResources(session.value,0,None,1,ctypes.byref(process),0,None)
        if code:raise OSError(code,'Cannot register owned native app')
        # Zero flags: unresponsive apps are never force-killed.
        code=manager.RmShutdown(session.value,0,None)
        return {'stopped':code==0,'error_code':code,'force':False}
    finally:manager.RmEndSession(session.value)
