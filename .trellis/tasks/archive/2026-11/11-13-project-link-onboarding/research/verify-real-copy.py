"""Read-only snapshot of user ledger; exercise opt-in only in the task-owned copy."""
from __future__ import annotations
import hashlib,json,os,shutil,sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from aha.storage import Store
ROOT=Path(os.environ['AHA_PROJECT_LINK_ROOT'])
RESEARCH=Path(__file__).resolve().parent
ORIGINAL=Path('C:/Users/djsyw/AppData/Local/aha')

def digests(db):
 result={}
 for name,sql in {
  'facts':'SELECT record_key,version_id,content_hash,total_cost_usd,total_tokens FROM usage_records ORDER BY record_key',
  'claims':'SELECT * FROM usage_claims ORDER BY record_key',
  'versions':'SELECT id,record_key,content_hash FROM usage_versions ORDER BY id',
 }.items():
  h=hashlib.sha256();n=0
  for row in db.execute(sql):h.update(json.dumps(tuple(row),ensure_ascii=False,separators=(',',':')).encode());n+=1
  result[name]={'count':n,'sha256':h.hexdigest()}
 costs=sum((Decimal(r[0]) for r in db.execute('SELECT total_cost_usd FROM usage_records WHERE suppressed=0')),Decimal(0))
 result['total_cost_usd']=str(costs)
 return result

def main():
 copy=ROOT/('real-ledger-copy-'+uuid4().hex[:8]);copy.mkdir()
 (copy/'.task-copy.json').write_text(json.dumps({'task':'project-link-onboarding','private_business_snapshot':True,'cleanup_after_delivery':True})+'\n')
 with closing(sqlite3.connect((ORIGINAL/'aha.sqlite3').as_uri()+'?mode=ro',uri=True)) as source:
  source.execute('PRAGMA query_only=ON');source.execute('PRAGMA trusted_schema=OFF')
  with closing(sqlite3.connect(copy/'aha.sqlite3')) as destination:source.backup(destination)
 # Keep private files outside Git; do not initialize Store on the original.
 for name in ('packages','objects'):
  if (ORIGINAL/name).is_dir():shutil.copytree(ORIGINAL/name,copy/name)
 material_before={str(p.relative_to(copy)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (copy/'packages').rglob('*.zip')}
 with closing(Store(copy)) as store:
  with store.read_connection() as db:before=digests(db)
  config=store.config();target=next(p for p in config['projects'] if 'himeko' in p['name'].lower())
  with store.read_connection() as db:
   assigned_before=db.execute('SELECT COUNT(*) FROM usage_records WHERE project_id=?',(target['id'],)).fetchone()[0]
   source_before=db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
  preview=store.preview_project_binding({'project_id':target['id'],'name':target['name'],'description':target['description'],'directories':target['directories']})
  # A preview must be read-only with respect to accepted members.
  with store.read_connection() as db:assert digests(db)==before
  result=store.apply_project_binding(preview['preview_id'],'real-copy-only-'+uuid4().hex)
  assert result['applied'] and result['project']['directory_managed']
  with store.read_connection() as db:
   after=digests(db);assigned_after=db.execute('SELECT COUNT(*) FROM usage_records WHERE project_id=?',(target['id'],)).fetchone()[0]
   assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==source_before
  assert after==before
  assert assigned_after>=preview['summary']['detail_count']
  material_after={str(p.relative_to(copy)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (copy/'packages').rglob('*.zip')}
  assert material_after==material_before
 report={'verified':True,'original_opened_mode':'ro/query_only','original_store_initialized':False,'business_writes_only_to_private_copy':True,'project_count_unchanged':True,'target_records_before':assigned_before,'target_records_after':assigned_after,'preview_detail_count':preview['summary']['detail_count'],'preview_changed_count':preview['summary']['changed_count'],'facts_versions_claims_and_total_cost_unchanged':after==before,'material_zip_count':len(material_before),'all_material_zip_bytes_unchanged':material_after==material_before}
 (RESEARCH/'real-copy-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
