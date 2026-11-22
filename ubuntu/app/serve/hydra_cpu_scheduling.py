"""Windows CPU efficiency classes, never guessed from logical processor order.

ABI/reference: https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-system_cpu_set_information
Higher EfficiencyClass means faster/less energy efficient; group0 only here.
"""
import ctypes,os,struct
import psutil
def parse_cpu_sets(raw):
 rows=[];offset=0
 while offset<len(raw):
  if len(raw)-offset<8:raise ValueError('CPU_SET_LAYOUT_TRUNCATED')
  size,kind=struct.unpack_from('<II',raw,offset)
  if size<8 or offset+size>len(raw):raise ValueError('CPU_SET_LAYOUT_INVALID')
  if kind==0:
   if size<32:raise ValueError('CPU_SET_LAYOUT_UNVERIFIED')
   rows.append(dict(group=struct.unpack_from('<H',raw,offset+12)[0],index=raw[offset+14],efficiency=raw[offset+18],flags=raw[offset+19]))
  offset+=size
 return rows
def ecore_indices(rows,allowed):
 group=[row for row in rows if row['group']==0 and row['index'] in allowed and not (row['flags']&2 and not row['flags']&4)]
 classes={row['efficiency'] for row in group}
 if len(classes)<2:return []
 return sorted(row['index'] for row in group if row['efficiency']==min(classes))
def topology():
 if os.name!='nt':return dict(available=False,reason='Windows CPU-set API unavailable',ecores=[])
 try:
  from ctypes import wintypes as W
  api=ctypes.WinDLL('kernel32',use_last_error=True).GetSystemCpuSetInformation
  api.argtypes=[W.LPVOID,W.DWORD,ctypes.POINTER(W.DWORD),W.HANDLE,W.DWORD];api.restype=W.BOOL
  length=W.DWORD();api(None,0,ctypes.byref(length),None,0)
  if not 0<length.value<=1024**2:raise ValueError('CPU_SET_SIZE_UNVERIFIED')
  buffer=ctypes.create_string_buffer(length.value)
  if not api(buffer,len(buffer),ctypes.byref(length),None,0):raise ctypes.WinError(ctypes.get_last_error())
  rows=parse_cpu_sets(buffer.raw[:length.value]);cores=ecore_indices(rows,psutil.Process().cpu_affinity())
  return dict(available=bool(cores),reason='Windows efficiency classes and allowed process mask verified' if cores else 'No distinct efficiency classes in allowed group0 CPU sets',ecores=cores,cpu_sets=rows)
 except (OSError,ValueError,AttributeError) as exc:return dict(available=False,reason=type(exc).__name__+': '+str(exc),ecores=[])
