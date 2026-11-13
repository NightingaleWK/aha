"""Create a task-owned runtime matching the identified public EXE without modifying base Python."""
from __future__ import annotations
import hashlib,json,os,shutil,sqlite3,subprocess,sys
from pathlib import Path
ROOT=Path('C:/Users/djsyw/AppData/Local/Temp/aha-project-link-20261113')
EXE=Path('D:/Program Files/aha.exe')
EXE_SHA='af79950072a347461f686f2c986d1a36182ceccab178aa3d8d926f49ca6dd01f'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 assert sys.platform=='win32' and tuple(sys.version_info[:3])==(3,15,2)
 assert json.loads((ROOT/'task-ownership.json').read_text())['task']=='project-link-onboarding'
 source=next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'src/aha').is_dir());research=Path(__file__).resolve().parent
 qa=ROOT/'qa315';python=qa/'Scripts/python.exe'
 sys.path.insert(0,str(qa/'Lib/site-packages'))
 from PyInstaller.archive.readers import CArchiveReader
 assert sha(EXE)==EXE_SHA
 archive=CArchiveReader(str(EXE));base=Path(sys.base_prefix)
 original={n:sha(base/'DLLs'/n) for n in ('sqlite3.dll','_sqlite3.pyd')}
 private=ROOT/'runtime315-sqlite3534'
 assert not private.exists();private.mkdir()
 (private/'runtime-ownership.json').write_text(json.dumps({'task':'project-link-onboarding','source_base':str(base)})+'\n')
 for item in base.iterdir():
  if item.is_file() and item.suffix.lower() in {'.dll','.exe','.txt','.json'}:
   assert not item.is_symlink();shutil.copy2(item,private/item.name)
 for n in ('DLLs','Lib','include','libs','tcl'):
  assert (base/n).is_dir() and not (base/n).is_symlink()
  shutil.copytree(base/n,private/n,ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc'))
 extracted={}
 for n in original:
  entries=[k for k in archive.toc if k.replace(chr(92),'/').split('/')[-1].lower()==n]
  assert len(entries)==1
  raw=archive.extract(entries[0]);assert raw.startswith(b'MZ') and len(raw)<8*1024*1024
  (private/'DLLs'/n).write_bytes(raw);extracted[n]=hashlib.sha256(raw).hexdigest()
 env=dict(os.environ,PIP_CACHE_DIR=str(ROOT/'pip-cache'),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
 def run(args):
  with (research/'native-setup.log').open('a',encoding='utf-8') as out:
   subprocess.run([str(a) for a in args],cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
 run([private/'python.exe','-m','venv','--upgrade','--without-pip',qa])
 wheel=ROOT/'provenance/wheel/zstandard-0.25.0-cp315-cp315-win_amd64.whl'
 assert sha(wheel)=='a1c09646b16f6c5c3dfbd6d2074bbe5bdb6cac88d1566762b6ad2d7b4003e178'
 run([python,'-m','pip','install','--no-index','--no-deps',wheel])
 run([python,'-m','pip','install','--no-index','-r',source/'scripts/requirements-build.txt'])
 metadata=ROOT/'metadata-source';metadata.mkdir()
 for n in ('pyproject.toml','README.md'):shutil.copy2(source/n,metadata/n)
 shutil.copytree(source/'src/aha',metadata/'src/aha',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 run([python,'-m','pip','install','--no-build-isolation','--no-deps',metadata])
 probe="import sys,sqlite3,json,zstandard;from importlib.metadata import version;assert sqlite3.sqlite_version_info==(3,53,4);assert sys.prefix!=sys.base_prefix;data=b'aha synthetic'*100;assert zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(data))==data;print(json.dumps({'verified':True,'python':list(sys.version_info[:3]),'sqlite':sqlite3.sqlite_version,'packages':{n:version(n) for n in ['pyinstaller','setuptools','wheel','zstandard','altgraph','packaging','pefile','pyinstaller-hooks-contrib','pywin32-ctypes']}}))"
 checked=subprocess.run([str(python),'-I','-c',probe],check=True,capture_output=True,text=True,env=env)
 report=json.loads(checked.stdout);report.update(qa_python=str(python),identified_public_exe_sha256=EXE_SHA,extracted_dll_sha256=extracted,base_runtime_unchanged={n:sha(base/'DLLs'/n) for n in original}==original)
 assert report['base_runtime_unchanged']
 (research/'native-environment.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(report),flush=True)
if __name__=='__main__':main()
