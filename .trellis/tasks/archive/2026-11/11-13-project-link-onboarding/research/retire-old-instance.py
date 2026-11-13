"""Normally stop only an identified old aha server so the new desktop EXE is not shadowed."""
from __future__ import annotations
import ctypes,json,socket,sys,time
from ctypes import wintypes
from pathlib import Path
SOURCE=next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'src/aha').is_dir())
RESEARCH=Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE/'scripts'))
import verify_windows_artifact as artifact

def main():
 delivery=json.loads((RESEARCH/'desktop-delivery.json').read_text());assert delivery['verified']
 descriptor=Path('C:/Users/djsyw/AppData/Local/aha/runtime.json')
 report={'verified':True,'source_sync_started':False,'business_records_changed':False}
 if not descriptor.exists():report['state']='no_existing_default_instance'
 else:
  launch=json.loads(descriptor.read_text());pid=launch['pid']
  kernel=ctypes.WinDLL('kernel32',use_last_error=True)
  kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
  kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)];kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
  kernel.CloseHandle.argtypes=[wintypes.HANDLE]
  handle=kernel.OpenProcess(0x1000,False,pid);assert handle
  try:
   length=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(length.value)
   assert kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(length))
   executable=Path(buffer.value).resolve(strict=True)
  finally:kernel.CloseHandle(handle)
  digest=artifact.digest(executable)
  if digest==delivery['executable_sha256']:
   report['state']='new_default_instance_already_running'
  else:
   assert digest=='af79950072a347461f686f2c986d1a36182ceccab178aa3d8d926f49ca6dd01f','Unidentified running instance was preserved.'
   client=artifact.Client(launch);client.json('POST','/api/shutdown',{})
   end=time.monotonic()+30
   while time.monotonic()<end:
    with socket.socket() as probe:closed=probe.connect_ex(('127.0.0.1',client.port))!=0
    if closed and not descriptor.exists():break
    time.sleep(.1)
   assert closed and not descriptor.exists(),'Known old instance did not shut down normally.'
   report.update(state='identified_old_default_instance_normally_stopped',old_executable_sha256=digest,forced_termination=False)
 (RESEARCH/'old-instance-transition.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
