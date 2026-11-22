"""Optional AMD driver sensor reads. No clock, voltage, power or fan setters."""
import ctypes as C
import os
import atexit

class Adapter(C.Structure):
    _fields_=[('size',C.c_int),('index',C.c_int),('udid',C.c_char*256),
              ('bus',C.c_int),('device',C.c_int),('function',C.c_int),('vendor',C.c_int),
              ('name',C.c_char*256),('display',C.c_char*256),('present',C.c_int),('exist',C.c_int),
              ('driver',C.c_char*256),('driver_ext',C.c_char*256),('pnp',C.c_char*256),('os_index',C.c_int)]
class Sensor(C.Structure):
    _fields_=[('supported',C.c_int),('value',C.c_int)]
class PMLog(C.Structure):
    _fields_=[('size',C.c_int),('sensors',Sensor*256)]

class Reader:
    def __init__(self, index=0):
        self.context=C.c_void_p();self.adapter=None;self.buffers=[]
        if os.name != 'nt':
            return
        self.dll=C.CDLL(os.path.join(os.environ.get('SystemRoot','C:/Windows'),'System32/atiadlxx.dll'))
        def allocate(size):
            if size <= 0 or size > 8*1024*1024:
                return None
            buffer=C.create_string_buffer(size);self.buffers.append(buffer)
            return C.addressof(buffer)
        self.callback=C.CFUNCTYPE(C.c_void_p,C.c_int)(allocate)
        def bind(name,types):
            f=getattr(self.dll,name);f.argtypes=types;f.restype=C.c_int;return f
        create=bind('ADL2_Main_Control_Create',[C.c_void_p,C.c_int,C.POINTER(C.c_void_p)])
        if create(self.callback,1,C.byref(self.context)) != 0:
            return
        atexit.register(self.close)
        number=C.c_int()
        if bind('ADL2_Adapter_NumberOfAdapters_Get',[C.c_void_p,C.POINTER(C.c_int)])(self.context,C.byref(number)) != 0:
            return
        if not 0 < number.value <= 64:
            return
        adapters=(Adapter*number.value)()
        for adapter in adapters:adapter.size=C.sizeof(Adapter)
        if bind('ADL2_Adapter_AdapterInfo_Get',[C.c_void_p,C.POINTER(Adapter),C.c_int])(self.context,adapters,C.sizeof(adapters)) != 0:
            return
        unique={}
        for adapter in adapters:
            if b'Radeon' in adapter.name and adapter.present:
                unique.setdefault(adapter.bus,adapter.index)
        if index < len(unique):self.adapter=list(unique.values())[index]
        self.query=bind('ADL2_New_QueryPMLogData_Get',[C.c_void_p,C.c_int,C.POINTER(PMLog)])

    def read(self):
        if self.adapter is None:return {}
        data=PMLog();data.size=C.sizeof(data)
        if self.query(self.context,self.adapter,C.byref(data)) != 0:return {}
        result={}
        for key,sensor_id,scale in [('temp',8,1),('vram_temp',9,1),('temp_hotspot',27,1),('power',73,1),('volt',21,.001)]:
            sensor=data.sensors[sensor_id]
            if sensor.supported and sensor.value > 0:result[key]=sensor.value*scale
        return result

    def close(self):
        if self.context.value:
            destroy=self.dll.ADL2_Main_Control_Destroy
            destroy.argtypes=[C.c_void_p];destroy.restype=C.c_int
            destroy(self.context)
            self.context=C.c_void_p()
            self.buffers.clear()
