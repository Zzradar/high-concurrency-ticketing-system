"""Report native CreateProcess error. A successful child stays suspended and is terminated before executing."""
import ctypes,ctypes.wintypes as w,hashlib,json,os
from pathlib import Path
p=Path(os.environ['LOCALAPPDATA'])/'ms-playwright/chromium-1243/chrome-win64/chrome.exe'
class Startup(ctypes.Structure):
 _fields_=[('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),('lpTitle',w.LPWSTR),('dwX',w.DWORD),('dwY',w.DWORD),('dwXSize',w.DWORD),('dwYSize',w.DWORD),('dwXCountChars',w.DWORD),('dwYCountChars',w.DWORD),('dwFillAttribute',w.DWORD),('dwFlags',w.DWORD),('wShowWindow',w.WORD),('cbReserved2',w.WORD),('lpReserved2',ctypes.POINTER(ctypes.c_byte)),('hStdInput',w.HANDLE),('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]
class Process(ctypes.Structure):_fields_=[('hProcess',w.HANDLE),('hThread',w.HANDLE),('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateProcessW.argtypes=[w.LPCWSTR,w.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,w.BOOL,w.DWORD,ctypes.c_void_p,w.LPCWSTR,ctypes.POINTER(Startup),ctypes.POINTER(Process)]
k.CreateProcessW.restype=w.BOOL
k.TerminateProcess.argtypes=[w.HANDLE,w.UINT];k.CloseHandle.argtypes=[w.HANDLE]
s=Startup();s.cb=ctypes.sizeof(s);info=Process()
ok=k.CreateProcessW(str(p),ctypes.create_unicode_buffer('"'+str(p)+'"'),None,None,False,0x4|0x08000000,None,str(p.parent),ctypes.byref(s),ctypes.byref(info))
code=ctypes.get_last_error()
if ok:
 k.TerminateProcess(info.hProcess,0);k.CloseHandle(info.hThread);k.CloseHandle(info.hProcess)
result={'executable':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'createSuspendedSucceeded':bool(ok),'winError':None if ok else code,'message':None if ok else ctypes.FormatError(code),'noBrowserCodeExecuted':True}
Path(__file__).with_suffix('.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
