"""Remove only inventoried idle task-owned QA/build/private-copy files after delivery."""
from __future__ import annotations
import hashlib,json,os,shutil,stat,subprocess,sys,time
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path('C:/Users/djsyw/AppData/Local/Temp/aha-project-link-20261113')
RESEARCH=Path(__file__).resolve().parent

def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 assert sys.platform=='win32' and not Path(sys.executable).is_relative_to(ROOT)
 assert ROOT.resolve()==ROOT and not ROOT.is_symlink()
 assert json.loads((ROOT/'task-ownership.json').read_text())=={'task':'project-link-onboarding','cleanup_after_delivery':True}
 delivery=json.loads((RESEARCH/'desktop-delivery.json').read_text());assert delivery['verified']
 desktop=Path(delivery['destination']);assert not desktop.is_relative_to(ROOT) and sha(desktop)==delivery['executable_sha256']
 assert json.loads((RESEARCH/'ui-desktop.json').read_text())['verified']
 final=json.loads((RESEARCH/'check-full-final-result.json').read_text());assert final['verified'] and final['returncode']==0
 ps="Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (($_.ExecutablePath -and $_.ExecutablePath.StartsWith('"+str(ROOT)+"',[System.StringComparison]::OrdinalIgnoreCase)) -or ($_.CommandLine -and $_.CommandLine.Contains('"+str(ROOT)+"') -and ($_.CommandLine.Contains('--data-dir') -or $_.CommandLine.Contains('--user-data-dir')))) } | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
 observed=subprocess.run(['powershell.exe','-NoProfile','-Command',ps],check=True,capture_output=True,text=True,encoding='utf-8')
 assert not observed.stdout.strip(),'Task-owned processes still running; preserve all files until closed.'
 exact={'task-ownership.json','qa315','bootstrap-requirements.txt','bootstrap.log','pip-cache','provenance','runtime-wheel.zip','wheel-source.json','runtime315-sqlite3534','metadata-source','pycache','ruff-cache','build','verify-directory','verify-onefile','verify-desktop','full-suite-detached-launcher.log','full-suite-detached-launcher.json'}
 prefixes=('profile-','mypy-','ui-','real-ledger-copy-')
 children=list(ROOT.iterdir())
 assert all(p.name in exact or p.name.startswith(prefixes) for p in children),[p.name for p in children if p.name not in exact and not p.name.startswith(prefixes)]
 for p in children:
  if p.name.startswith('real-ledger-copy-'):
   assert json.loads((p/'.task-copy.json').read_text())['task']=='project-link-onboarding'
  if p.name.startswith('ui-') or p.name.startswith('verify-'):
   assert json.loads((p/'.aha-artifact-verification.json').read_text())['owner']=='aha-artifact-verification'
 stack=[ROOT];junctions=[];total=0;files=0
 while stack:
  for entry in os.scandir(stack.pop()):
   p=Path(entry.path);s=entry.stat(follow_symlinks=False)
   if getattr(s,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
    assert p.name=='Content.IE5' and getattr(s,'st_reparse_tag',None)==stat.IO_REPARSE_TAG_MOUNT_POINT
    target=Path(os.readlink(p).removeprefix('\\\\?\\'))
    assert target.resolve().is_relative_to(ROOT) and target.resolve()==p.with_name('IE').resolve()
    junctions.append(p)
   elif entry.is_dir(follow_symlinks=False):stack.append(p)
   else:total+=s.st_size;files+=1
 # Do not traverse a junction during deletion; only unlink the verified link itself.
 for p in junctions:p.rmdir()
 shutil.rmtree(ROOT)
 assert not ROOT.exists() and sha(desktop)==delivery['executable_sha256']
 report={'verified':True,'root':str(ROOT),'bytes_removed':total,'files_removed':files,'root_entries':sorted(p.name for p in children),'verified_junctions_unlinked':len(junctions),'real_user_sources_preserved':True,'desktop_sha256_unchanged':True,'active_task_processes':0,'completed_at':datetime.now(timezone(timedelta(hours=8))).isoformat()}
 (RESEARCH/'cleanup-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
