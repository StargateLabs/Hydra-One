"""Export original Windows icon resources without redrawing their artwork."""
import ctypes,hashlib,json,struct
from ctypes import wintypes
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def export_icon(path,target):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LoadLibraryExW.argtypes=[wintypes.LPCWSTR,wintypes.HANDLE,wintypes.DWORD];kernel.LoadLibraryExW.restype=wintypes.HMODULE
    kernel.FindResourceW.argtypes=[wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p];kernel.FindResourceW.restype=wintypes.HANDLE
    kernel.LoadResource.argtypes=[wintypes.HMODULE,wintypes.HANDLE];kernel.LoadResource.restype=wintypes.HANDLE
    kernel.LockResource.argtypes=[wintypes.HANDLE];kernel.LockResource.restype=ctypes.c_void_p
    kernel.SizeofResource.argtypes=[wintypes.HMODULE,wintypes.HANDLE];kernel.SizeofResource.restype=wintypes.DWORD
    kernel.FreeLibrary.argtypes=[wintypes.HMODULE]
    library=kernel.LoadLibraryExW(str(path),None,2)
    if not library:raise ctypes.WinError(ctypes.get_last_error())
    def read(name,kind):
        name_arg=ctypes.c_void_p(name) if isinstance(name,int) else ctypes.cast(ctypes.c_wchar_p(name),ctypes.c_void_p)
        resource=kernel.FindResourceW(library,name_arg,ctypes.c_void_p(kind))
        if not resource:raise ctypes.WinError(ctypes.get_last_error())
        loaded=kernel.LoadResource(library,resource)
        return ctypes.string_at(kernel.LockResource(loaded),kernel.SizeofResource(library,resource))
    try:
        names=[];callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMODULE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ssize_t)
        def enumerate_name(module,kind,name,parameter):
            names.append(name if name<=65535 else ctypes.wstring_at(name));return True
        callback=callback_type(enumerate_name)
        kernel.EnumResourceNamesW.argtypes=[wintypes.HMODULE,ctypes.c_void_p,callback_type,ctypes.c_ssize_t]
        kernel.EnumResourceNamesW(library,ctypes.c_void_p(14),callback,0)
        if not names:raise ValueError('Original application has no icon group')
        group=read(names[0],14);reserved,kind,count=struct.unpack_from('<HHH',group);entries=[];images=[];offset=6+16*count
        for index in range(count):
            width,height,colors,unused,planes,bits,size,identity=struct.unpack_from('<BBBBHHIH',group,6+14*index)
            image=read(identity,3);entries.append(struct.pack('<BBBBHHII',width,height,colors,unused,planes,bits,len(image),offset));images.append(image);offset+=len(image)
        target.write_bytes(struct.pack('<HHH',0,1,count)+b''.join(entries)+b''.join(images))
        result={'file':target.name,'source':str(path),'source_type':'original_installed_application_resource','sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'original_icon_images':count,'original_pixels':True}
        pngs=[raw for raw in images if raw.startswith(b'\x89PNG\r\n\x1a\n')]
        if pngs:
            png=max(pngs,key=lambda raw:struct.unpack_from('>I',raw,16)[0]);target.with_suffix('.png').write_bytes(png)
            result['original_png_file']=target.with_suffix('.png').name;result['original_png_sha256']=hashlib.sha256(png).hexdigest()
        return result
    finally:kernel.FreeLibrary(library)
def main():
    import sys
    sys.path.insert(0,str(ROOT))
    from serve.antigravity_desktop import executable as antigravity
    from serve.claude_desktop import executable as claude
    from serve.voicestudio import desktop_executable
    path=ROOT/'serve/web/brands/OFFICIAL-ASSETS.json';records=json.loads(path.read_text())
    for name,resolve in [('antigravity',antigravity),('claude-desktop',claude),('voicestudio',desktop_executable)]:
        executable=resolve()
        if executable is None:raise ValueError('Original app not installed: '+name)
        target=ROOT/'serve/web'/('brand-'+name+'.ico');records[name]=export_icon(executable,target);print(name+': exported original icon',flush=True)
    path.write_text(json.dumps(records,indent=2),encoding='utf-8')
if __name__=='__main__':main()
