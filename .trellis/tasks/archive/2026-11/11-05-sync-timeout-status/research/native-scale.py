"""Task-owned native EXE regression. Synthetic sources only; no production data."""
from __future__ import annotations
import argparse, json, runpy, sqlite3, subprocess, sys, time
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--exe',type=Path,required=True)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--keep-open',action='store_true')
    args=p.parse_args()
    sys.path.insert(0,str(args.source_root/'scripts'))
    sys.path.insert(0,str(args.source_root/'src'))
    from verify_windows_artifact import isolated_environment,Client,wait_descriptor,check_shutdown,stop_process,digest,require,BEIJING
    env,profile=isolated_environment(args.data_root)
    fx=runpy.run_path(str(args.source_root/'tests/test_sources.py'))
    n=30000
    event=int(datetime.fromisoformat('2026-11-05T08:00:00+08:00').timestamp())
    rows=[fx['detail'](request_id=f'scale-{i:06}',session_id=None,model='m',created_at=event+i,total_cost_usd='0.190000001') for i in range(n)]
    source=profile/'.cc-switch/cc-switch.db'
    with closing(fx['database'](source,rows,version=24)) as c:
        aggregate=fx['rollup'](date='2026-11-04')
        fields=fx['ROLLUP_FIELDS']
        c.execute('INSERT INTO usage_daily_rollups VALUES ('+','.join('?' for _ in fields)+')',[aggregate[f] for f in fields])
        c.commit()
    del rows
    data=args.data_root/'store'
    descriptor=data/'runtime.json'
    command=[str(args.exe),'--data-dir',str(data),'--no-browser','--no-tray']
    process=subprocess.Popen(command,cwd=profile,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    client=None
    report={'schema_version':1,'executable_sha256':digest(args.exe),'synthetic_rows':n,'runs':[],'verified':False}
    def sync(body):
        began=time.perf_counter()
        job=client.json('POST','/api/sync',body)
        deadline=time.monotonic()+180
        while job['status']=='running':
            require(time.monotonic()<deadline,'Scale sync exceeded diagnostic budget')
            time.sleep(.1)
            job=client.json('GET','/api/sync/'+job['id'])
        report['runs'].append({'status':job['status'],'elapsed_ms':round((time.perf_counter()-began)*1000,2),'timings_ms':job.get('result',{}).get('timings_ms'), 'new_count':job.get('result',{}).get('new_count')})
        return job
    try:
        client=Client(wait_descriptor(descriptor,process))
        for iteration in range(2):
            job=sync({'trigger':'startup'} if iteration==0 else {})
            require(job['status']=='completed','Scale synchronization did not complete')
            require(job['result']['source_schema_version']==24,'Source schema observation changed')
            if iteration:require(job['result']['new_count']==0,'Repeated sync duplicated usage')
        analysis=client.json('POST','/api/analysis',{'start_date':'2026-11-05','end_date':'2026-11-05','project_id':'all','availability_mode':'available'})
        require(analysis['summary']['record_count']==n,'Scale row count changed')
        require(Decimal(analysis['summary']['total_cost_usd'])==Decimal('0.190000001')*n,'Scale cost changed')
        require(analysis['summary']['total_tokens']==105*n,'Scale token count changed')
        report['summary']=analysis['summary']
        before=client.json('GET','/api/ledger')
        with closing(sqlite3.connect(source)) as c:c.execute('PRAGMA user_version=25');c.commit()
        require(sync({})['status']=='failed','Unsupported source did not fail')
        failed=client.json('GET','/api/ledger')
        require(failed['counts']==before['counts'] and failed['last_successful_sync_at']==before['last_successful_sync_at'],'Failure changed old published state')
        require(failed['last_attempt']['error_code']=='unsupported_schema','Failure reason was lost')
        with closing(sqlite3.connect(source)) as c:c.execute('PRAGMA user_version=24');c.commit()
        require(sync({})['status']=='completed','Retry did not recover')
        require(not list((data/'temporary').iterdir()),'Projection temporary files remain')
        if args.keep_open:
            with closing(sqlite3.connect(source)) as c:c.execute('PRAGMA user_version=25');c.commit()
            require(sync({})['status']=='failed','Browser failure setup did not fail')
            report['kept_open_for_browser']=True
            report['pid']=process.pid
            report['origin']=client.origin
        else:
            check_shutdown(client,process,descriptor)
            report['shutdown_verified']=True
        report['verified']=True
        report['verified_at']=datetime.now(BEIJING).isoformat()
    finally:
        if not (args.keep_open and report['verified']):stop_process(process,client)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__':main()
