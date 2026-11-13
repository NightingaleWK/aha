"""Exercise the directory project workflow in native Edge against isolated data."""
from __future__ import annotations
import argparse,hashlib,json,os,runpy,sqlite3,subprocess,sys,time
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
SOURCE=next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'src/aha').is_dir())
RESEARCH=Path(__file__).resolve().parent
ROOT=Path(os.environ['AHA_PROJECT_LINK_ROOT'])
SHOTS=Path('C:/Users/djsyw/.codex/visualizations/2026/11/13/01a1d2b9-1dc4-7ef0-b130-8e2be6af3f48/aha-project-link')
sys.path.insert(0,str(SOURCE/'scripts'))
import verify_windows_artifact as artifact

def main():
 from playwright.sync_api import sync_playwright,expect
 from aha.storage import Store
 from aha.sources import load_sqlite
 from aha.session_meta import scan_metadata
 from aha.domain import DETAIL_FIELDS,record_key
 parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path);parser.add_argument('--label',required=True);args=parser.parse_args()
 case=ROOT/('ui-'+args.label+'-'+uuid4().hex[:8]);env,profile=artifact.isolated_environment(case)
 os.environ.update(env)
 fixtures=runpy.run_path(str(SOURCE/'tests/test_sources.py'))
 ids=[str(uuid4()) for _ in range(4)];known,other,late,future=ids
 paths={known:'/synthetic/himeko',other:'/synthetic/other',late:'/synthetic/himeko',future:'/synthetic/himeko'}
 headers=profile/'.codex/sessions';headers.mkdir(parents=True)
 def header(sid):
  (headers/('rollout-'+sid+'.jsonl')).write_text(json.dumps({'type':'session_meta','payload':{'id':sid,'cwd':paths[sid]}})+'\n',encoding='utf-8')
 for sid in (known,other):header(sid)
 event=int(datetime.now(timezone.utc).timestamp())-120
 rows=[fixtures['detail'](request_id='ui-'+str(n),session_id=known,created_at=event+n,total_cost_usd='0.190000001') for n in range(65)]
 rows += [fixtures['detail'](request_id='ui-other',session_id=other,created_at=event+70),fixtures['detail'](request_id='ui-late',session_id=late,created_at=event+71)]
 source=profile/'.cc-switch/cc-switch.db';fixtures['database'](source,rows,version=26).close()
 store_dir=case/'store'
 with closing(Store(store_dir)) as store:
  store.sync_data(load_sqlite(source),scan_metadata(set(ids),[profile/'.codex']),trust='live')
  legacy=store.save_project(None,'旧人工项目','合成验收',['/synthetic/old'])['project']['id']
  store.assign_keys([record_key(rows[0])],legacy)
 env['PYTHONPATH']=os.pathsep.join((str(SOURCE/'src'),str(SOURCE)))
 command=[str(args.exe)] if args.exe else [sys.executable,'-B','-m','aha']
 command += ['--data-dir',str(store_dir),'--no-browser']
 descriptor=store_dir/'runtime.json';process=subprocess.Popen(command,cwd=profile,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 client=None;SHOTS.mkdir(parents=True,exist_ok=True);checks={};screens=[]
 def count(pid):
  with closing(sqlite3.connect(store_dir/'aha.sqlite3')) as db:return db.execute('SELECT COUNT(*) FROM usage_records WHERE project_id=? AND suppressed=0',(pid,)).fetchone()[0]
 def wait_count(pid,n):
  until=time.monotonic()+20
  while time.monotonic()<until:
   if count(pid)==n:return
   time.sleep(.1)
  raise AssertionError(('count',n,count(pid)))
 def add_row(name,sid,offset):
  row=fixtures['detail'](request_id=name,session_id=sid,created_at=event+offset,total_cost_usd='0.190000001')
  with closing(sqlite3.connect(source)) as db:
   db.execute('INSERT INTO proxy_request_logs VALUES ('+','.join('?' for _ in DETAIL_FIELDS)+')',[row[k] for k in DETAIL_FIELDS]);db.commit()
 try:
  launch=artifact.wait_descriptor(descriptor,process);client=artifact.Client(launch)
  binding=client.json('GET','/api/source/binding')
  if binding.get('required'):client.json('POST','/api/source/binding',{'reason':'合成验收：确认隔离来源，保留既有历史。'})
  assert client.sync({})['status']=='completed'
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
   page=browser.new_page(locale='zh-CN',viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
   try:
    page.goto(launch['bootstrap_url']);expect(page.locator('#source-mode')).to_have_text('已同步',timeout=30000)
    page.locator('[data-page="projects"]').click();expect(page.locator('#new-project')).to_be_visible()
    def choose(name,path):
     page.locator('#new-project').click();page.locator('#edit-project-name').fill(name)
     candidate=page.locator('#project-candidates input[value="'+path+'"]')
     if candidate.count():candidate.check()
     else:page.locator('#edit-project-directories').fill(path)
     page.locator('#preview-project-binding').click();expect(page.locator('#project-binding-impact')).to_be_visible();expect(page.locator('#apply-project-binding')).to_be_enabled()
    choose('姬子合成验收','/synthetic/himeko')
    expect(page.locator('#project-binding-summary')).to_contain_text('65')
    expect(page.locator('#project-binding-changes')).to_contain_text('旧人工项目')
    assert len(client.json('GET','/api/projects')['projects'])==1
    assert page.locator('#project-binding-impact input[type=checkbox]').count()==0
    previewshot=SHOTS/(args.label+'-impact.png');page.screenshot(path=str(previewshot),full_page=True);screens.append(str(previewshot))
    page.locator('#back-project-editor').click();expect(page.locator('#project-editor')).to_be_visible()
    assert len(client.json('GET','/api/projects')['projects'])==1
    page.locator('#preview-project-binding').click();expect(page.locator('#apply-project-binding')).to_be_enabled();page.locator('#apply-project-binding').click();expect(page.locator('#project-dialog')).not_to_be_visible(timeout=30000)
    config=client.json('GET','/api/projects');target=next(p['id'] for p in config['projects'] if p['name']=='姬子合成验收');wait_count(target,65);assert count(legacy)==0
    checks.update(full_65_record_history=True,old_manual_override_transferred=True,cancelled_preview_has_no_project_write=True,no_record_selection_required=True)
    header(future);add_row('ui-added-known',known,80);add_row('ui-added-future',future,81)
    page.locator('[data-page="usage"]').click();page.locator('#load-default').click();expect(page.locator('#source-mode')).to_have_text('已同步',timeout=30000);wait_count(target,67);page.locator('[data-page="projects"]').click()
    checks['existing_and_new_session_future_usage']=True
    header(late)
    page.locator('summary.metadata-toggle').click();page.locator('#refresh-metadata').click();page.locator('#scan-metadata').click();wait_count(target,68);expect(page.locator('#source-dialog')).not_to_be_visible()
    checks['late_directory_recognition']=True
    choose('统一转入项目','/synthetic/himeko');expect(page.locator('#project-binding-transfers')).to_contain_text('姬子合成验收');expect(page.locator('#project-binding-summary')).to_contain_text('68')
    page.locator('#apply-project-binding').click();expect(page.locator('#project-dialog')).not_to_be_visible(timeout=30000)
    config=client.json('GET','/api/projects');second=next(p['id'] for p in config['projects'] if p['name']=='统一转入项目');wait_count(second,68);assert count(target)==0
    assert next(p for p in config['projects'] if p['id']==target)['directories']==[]
    add_row('ui-after-transfer',known,82);page.locator('[data-page="usage"]').click();page.locator('#load-default').click();expect(page.locator('#source-mode')).to_have_text('已同步',timeout=30000);wait_count(second,69);page.locator('[data-page="projects"]').click()
    checks['directory_transfer_updates_both_projects_and_future_usage']=True
    choose('零历史目录合成验收','/synthetic/empty');expect(page.locator('#project-binding-summary')).to_contain_text('0');page.locator('#apply-project-binding').click();expect(page.locator('#project-dialog')).not_to_be_visible(timeout=30000)
    checks['zero_history_binding']=True
    cards=page.locator('#project-list .project-card');target_card=cards.filter(has_text='统一转入项目');target_card.get_by_role('button',name='管理目录').click()
    page.locator('#edit-project-name').fill('统一转入项目：长名称与新旧机器目录的完整显示测试')
    page.locator('#edit-project-directories').fill('/old-device/himeko\nC:/synthetic/old-device/himeko')
    page.locator('#preview-project-binding').click();expect(page.locator('#apply-project-binding')).to_be_enabled()
    for width in (1366,1280,430,375):
     page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(100)
     assert page.locator('#apply-project-binding').is_enabled()
     metrics=page.locator('#project-dialog').evaluate('(el)=>({client:el.clientWidth,scroll:el.scrollWidth})')
     assert metrics['scroll']<=metrics['client']+2,metrics
     if width==375:
      shot=SHOTS/(args.label+'-mobile.png');page.screenshot(path=str(shot),full_page=True);screens.append(str(shot))
    page.keyboard.press('Escape');expect(page.locator('#project-dialog')).not_to_be_visible()
    checks['keyboard_escape_and_responsive_1440_1366_1280_430_375']=True
    page.set_viewport_size({'width':1440,'height':1000});shot=SHOTS/(args.label+'-projects.png');page.screenshot(path=str(shot),full_page=True);screens.append(str(shot))
    assert not errors,errors
    checks['no_javascript_page_errors']=True
   except BaseException:
    page.screenshot(path=str(SHOTS/(args.label+'-failure.png')),full_page=True);raise
   finally:browser.close()
  artifact.check_shutdown(client,process,descriptor);checks['native_exit_descriptor_cleanup']=not descriptor.exists()
  report={'verified':True,'label':args.label,'native_edge':True,'headless':True,'tray_enabled':True,'physical_tray_input':False,'synthetic_data_only':True,'checks':checks,'screenshots':screens,'executable_sha256':artifact.digest(args.exe) if args.exe else None}
  (RESEARCH/('ui-'+args.label+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
 finally:artifact.stop_process(process,client)
if __name__=='__main__':main()
