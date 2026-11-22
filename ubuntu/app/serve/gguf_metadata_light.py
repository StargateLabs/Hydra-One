"""Read a selected GGUF metadata string without materializing embedded assets."""
import struct

def metadata_string(path,wanted):
 sizes={0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:1,10:8,11:8,12:8}
 with open(path,'rb') as stream:
  def integer(fmt):
   size=struct.calcsize(fmt);raw=stream.read(size)
   if len(raw)!=size:raise ValueError('Truncated GGUF metadata')
   return struct.unpack(fmt,raw)[0]
  def string():
   length=integer('<Q')
   if length>2*1024**2:raise ValueError('Metadata string too large')
   raw=stream.read(length)
   if len(raw)!=length:raise ValueError('Truncated metadata string')
   return raw.decode('utf-8')
  if stream.read(4)!=b'GGUF' or integer('<I')!=3:raise ValueError('GGUF v3 required')
  integer('<Q');count=integer('<Q')
  if count>10000:raise ValueError('Metadata count exceeds limit')
  for _ in range(count):
   name=string();kind=integer('<I')
   if kind==8:
    value=string()
    if name==wanted:return value
   elif kind==9:
    subtype=integer('<I');length=integer('<Q')
    if subtype==8:
     if length>1000000:raise ValueError('String array too large')
     for _ in range(length):
      size=integer('<Q')
      if size>2*1024**2:raise ValueError('Metadata string too large')
      stream.seek(size,1)
    elif subtype in sizes:stream.seek(length*sizes[subtype],1)
    else:raise ValueError('Unsupported metadata array')
   elif kind in sizes:stream.seek(sizes[kind],1)
   else:raise ValueError('Unsupported metadata type')
 return None
