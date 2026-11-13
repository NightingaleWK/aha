"""Deliver only the validated OneFile, then verify that exact desktop copy in isolation."""
from __future__ import annotations
import ctypes,json,os,shutil,sys
from pathlib import Path
from uuid import uuid4
ROOT=Path(os.environ['AHA_PROJECT_LINK_ROOT'])
SOURCE=next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'src/aha').is_dir())
RESEARCH=Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE/'scripts'))
import verify_windows_artifact as artifact

def main():
 assert sys.platform=='win32'
 assert json.loads((ROOT/'task-ownership.json').read_text())['task']=='project-link-onboarding'
 validated=json.loads((RESEARCH/'onefile-verification.json').read_text())
 ui=json.loads((RESEARCH/'ui-onefile.json').read_text())
 assert validated['verified'] and ui['verified']
 original=ROOT/'build/release/portable/aha.exe';expected=validated['executable_sha256']
 assert artifact.digest(original)==expected==ui['executable_sha256']
 buffer=ctypes.create_unicode_buffer(32768);shell=ctypes.WinDLL('shell32',use_last_error=True)
 shell.SHGetFolderPathW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_wchar_p];shell.SHGetFolderPathW.restype=ctypes.c_long
 assert shell.SHGetFolderPathW(None,0x10,None,0,buffer)==0
 desktop=Path(buffer.value).resolve(strict=True);destination=desktop/'aha.exe';backup=None
 if destination.exists():
  assert destination.is_file() and not destination.is_symlink()
  prior=artifact.digest(destination)
  if prior!=expected:
   assert prior=='af79950072a347461f686f2c986d1a36182ceccab178aa3d8d926f49ca6dd01f','Unidentified desktop executable is preserved.'
   backup_root=Path('C:/Users/djsyw/AppData/Local/aha-program-backups')/('before-directory-binding-'+prior[:12]);backup_root.mkdir(parents=True,exist_ok=True)
   backup=backup_root/'aha.exe'
   if backup.exists():assert artifact.digest(backup)==prior
   else:shutil.copy2(destination,backup)
 temp=desktop/('.aha-directory-binding-'+uuid4().hex+'.exe')
 try:
  shutil.copy2(original,temp);assert artifact.digest(temp)==expected;os.replace(temp,destination)
 finally:temp.unlink(missing_ok=True)
 report={'verified':False,'destination':str(destination),'version':validated['version'],'executable_sha256':expected,'single_file':True,'known_folder_checked':True,'backup':str(backup) if backup else None,'genuine_aha_business_writes':False,'source_basis':json.loads((RESEARCH/'source-fingerprints.json').read_text())}
 (RESEARCH/'desktop-delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 checked=artifact.verify(destination,SOURCE,ROOT/'verify-desktop',with_tray=True)
 assert checked['verified'] and checked['executable_sha256']==expected
 (RESEARCH/'desktop-verification.json').write_text(json.dumps(checked,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report.update(verified=True,from_desktop_executable_run=True,isolated_data_checked=True,sha_matches_validated_onefile=artifact.digest(destination)==expected,shutdown_descriptor_cleaned=True)
 (RESEARCH/'desktop-delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
