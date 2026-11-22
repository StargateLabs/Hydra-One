"""One connection, one in-flight request, no implicit retry. Laboratory only."""
import http.client,threading,ipaddress,math,time

def local_endpoint(host,port,timeout):
 if host=='localhost':host='127.0.0.1'
 try:local=ipaddress.ip_address(host).is_loopback
 except (ValueError,TypeError):local=False
 if not local or type(port) is not int or not 1<=port<=65535:raise ValueError('HTTP_POOL_LOCAL_ENDPOINT_REQUIRED')
 if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=3600:raise ValueError('HTTP_POOL_FINITE_TIMEOUT_REQUIRED')
 return host

class SerialConnectionPool:
 def __init__(self,factory=http.client.HTTPConnection):
  self.factory=factory;self.idle=None;self.active=None;self.lock=threading.Lock();self.closed=False
  self.stats=dict(created=0,reused=0,discarded=0,closed=0)
 def connection(self,host,port,timeout):
  host=local_endpoint(host,port,timeout)
  with self.lock:
   if self.closed:raise RuntimeError('HTTP_POOL_CLOSED')
   if self.active is not None:raise RuntimeError('HTTP_POOL_BUSY; one request at a time')
   key=(host,port)
   if self.idle is not None and time.monotonic()-self.idle[2]>30:
    self.idle[1].close();self.idle=None;self.stats['closed']+=1
   if self.idle is not None and self.idle[0]==key:
    raw=self.idle[1];self.idle=None;raw.timeout=timeout
    try:
     setter=getattr(raw.sock,'settimeout',None)
     if setter is not None:setter(timeout)
    except BaseException:
     raw.close();self.stats['discarded']+=1;raise
    self.stats['reused']+=1
   else:
    if self.idle is not None:self.idle[1].close();self.idle=None;self.stats['closed']+=1
    raw=self.factory(host,port,timeout=timeout);self.stats['created']+=1
   raw.auto_open=0 # reconnect must pass through the revocable lease, including cancellation races
   proxy=_Connection(self,key,raw);self.active=proxy;return proxy
 def release(self,proxy):
  with self.lock:
   proxy.released=True
   if self.active is not proxy:return
   response=proxy.response
   reusable=not self.closed and response is not None and response.isclosed() and (response.length==0 or getattr(response,'_hydra_body_consumed',False) is True) and not response.will_close and proxy.raw.sock is not None
   if reusable:self.idle=(proxy.key,proxy.raw,time.monotonic())
   else:proxy.raw.close();self.stats['discarded']+=1
   self.active=None
 def close(self):
  with self.lock:
   self.closed=True
   errors=[]
   if self.idle is not None:
    try:self.idle[1].close();self.idle=None;self.stats['closed']+=1
    except Exception as exc:errors.append(exc)
   if self.active is not None:
    self.active.released=True
    try:self.active.raw.close();self.active=None;self.stats['closed']+=1
    except Exception as exc:errors.append(exc)
   if errors:raise RuntimeError('HTTP_POOL_CLEANUP_UNVERIFIED: '+str(errors[0])) from errors[0]
class _Connection:
 def __init__(self,pool,key,raw):self.pool=pool;self.key=key;self.raw=raw;self.response=None;self.released=False
 def _ensure_active(self):
  if self.released or self.pool.closed or self.pool.active is not self:raise RuntimeError('HTTP_POOL_LEASE_REVOKED')
 def __getattr__(self,name):self._ensure_active();return getattr(self.raw,name)
 def connect(self):
  self._ensure_active()
  if self.raw.sock is None:self.raw.connect()
  try:self._ensure_active()
  except RuntimeError:self.raw.close();raise
 def request(self,*args,**kwargs):
  self.connect();result=self.raw.request(*args,**kwargs)
  self._ensure_active();return result
 def getresponse(self):
  self._ensure_active();response=self.raw.getresponse()
  try:self._ensure_active()
  except RuntimeError:
   response.close();raise
  self.response=response;return response
 def close(self):self.pool.release(self)
