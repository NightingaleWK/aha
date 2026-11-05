"""Task-owned native Edge and Office verification of synthetic artifacts."""
from __future__ import annotations
import argparse,csv,hashlib,json,sqlite3,subprocess,sys,uuid
from contextlib import closing
from pathlib import Path
from decimal import Decimal
from datetime import datetime


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--material',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.source_root/'scripts'))
    from verify_windows_artifact import Client,require,BEIJING,isolated_environment,wait_descriptor,stop_process,check_shutdown
    from playwright.sync_api import sync_playwright,expect
    from pypdf import PdfReader
    import win32com.client
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    descriptor=json.loads((args.data_root/'store/runtime.json').read_text())
    client=Client(descriptor)
    report={'verified':False,'browser':'native Microsoft Edge','screens':[],'console_errors':[]}
    source=args.data_root/'synthetic-profile/.cc-switch/cc-switch.db'
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=False,args=['--no-first-run','--no-default-browser-check'])
        try:
            context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN',timezone_id='Asia/Shanghai')
            page=context.new_page()
            page.on('pageerror',lambda error:report['console_errors'].append(str(error)))
            page.goto(descriptor['bootstrap_url'])
            expect(page.locator('#source-mode')).to_have_text('同步失败',timeout=30000)
            expect(page.locator('#sync-error')).to_contain_text('当前显示已保存的本地数据')
            expect(page.locator('#source-description')).to_contain_text('30,000')
            expect(page.locator('#metric-count')).to_contain_text('30,000',timeout=30000)
            expect(page.locator('#metric-tokens')).to_contain_text('3,150,000')
            for width in (1440,1366,1280,430,375):
                page.set_viewport_size({'width':width,'height':1000})
                expect(page.locator('#sync-error')).to_be_visible()
                name=f'failed-{width}.png'
                page.screenshot(path=str(output/name),full_page=False)
                geometry=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
                require(geometry['scroll']<=geometry['width']+1,'Page horizontally overflows')
                report['screens'].append({'file':name,'width':width,'horizontal_overflow':False})
            page.reload()
            expect(page.locator('#source-mode')).to_have_text('同步失败')
            with closing(sqlite3.connect(source)) as c:c.execute('PRAGMA user_version=24');c.commit()
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('#load-default').click()
            expect(page.locator('#source-mode')).to_have_text('同步中',timeout=3000)
            expect(page.locator('#sync-error')).to_be_hidden()
            expect(page.locator('#load-default')).to_be_disabled()
            expect(page.locator('#source-mode')).to_have_text('已同步',timeout=120000)
            expect(page.locator('#load-default')).to_be_enabled()
            expect(page.locator('#source-description')).to_contain_text('30,000')
            expect(page.locator('#sync-error')).to_be_hidden()
            page.screenshot(path=str(output/'recovered-1440.png'))
            page.reload()
            expect(page.locator('#source-mode')).to_have_text('已同步')
            require(not report['console_errors'],'Browser JavaScript errors observed')
            with closing(sqlite3.connect(source)) as c:c.execute('DELETE FROM proxy_request_logs');c.commit()
            page.locator('#load-default').click()
            expect(page.locator('#source-mode')).to_have_text('需要核对',timeout=120000)
            expect(page.locator('#sync-error')).to_be_hidden()
            page.reload()
            expect(page.locator('#source-mode')).to_have_text('需要核对')
            page.screenshot(path=str(output/'needs-review-1440.png'))
            empty_root=args.data_root.parent/('browser-empty-'+uuid.uuid4().hex[:8])
            empty_env,empty_profile=isolated_environment(empty_root)
            empty_data=empty_root/'store'
            process=subprocess.Popen([str(args.exe),'--data-dir',str(empty_data),'--no-browser','--no-tray'],cwd=empty_profile,env=empty_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            empty_client=None
            try:
                launch=wait_descriptor(empty_data/'runtime.json',process)
                empty_client=Client(launch)
                require(empty_client.sync({'trigger':'startup'})['status']=='failed','No-history missing source was not rejected')
                empty_page=context.new_page()
                empty_page.goto(launch['bootstrap_url'])
                expect(empty_page.locator('#source-mode')).to_have_text('同步失败',timeout=30000)
                expect(empty_page.locator('#sync-error')).to_contain_text('当前统计不代表实际用量')
                empty_page.reload()
                expect(empty_page.locator('#source-mode')).to_have_text('同步失败')
                empty_page.screenshot(path=str(output/'failed-no-history-1440.png'))
                empty_page.close()
                check_shutdown(empty_client,process,empty_data/'runtime.json')
            finally:stop_process(process,empty_client)
            report['browser_checks']=['failed-with-history','five-viewports','refresh-failure','retry-running','retry-completed','refresh-success','needs-review','refresh-needs-review','failed-no-history','no-console-error']
            report['browser_version']=browser.version
            (output/'browser-stage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        finally:browser.close()
        renderer=p.chromium.launch(executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',headless=True)
        try:
            page=renderer.new_page(locale='zh-CN')
            page.goto((args.material/'费用说明.html').as_uri())
            require('0.570000003' in page.locator('body').inner_text(),'Printed report precise amount absent')
            page.pdf(path=str(output/'synthetic-material-a4.pdf'),format='A4',print_background=True,prefer_css_page_size=True)
        finally:renderer.close()
    pdf=PdfReader(output/'synthetic-material-a4.pdf')
    text='\n'.join(page.extract_text() for page in pdf.pages)
    require('0.570000003' in text,'PDF lost precise amount')
    sizes=[[float(page.mediabox.width),float(page.mediabox.height)] for page in pdf.pages]
    require(all(abs(width-595.28)<2 and abs(height-841.89)<2 for width,height in sizes),'PDF is not A4')
    report['print']={'pages':len(pdf.pages),'page_sizes_pt':sizes,'amount_preserved':True,'file_sha256':hashlib.sha256((output/'synthetic-material-a4.pdf').read_bytes()).hexdigest()}
    csv_path=args.material/'使用明细.csv'
    with csv_path.open(encoding='utf-8-sig',newline='') as stream:expected=list(csv.reader(stream))
    excel=win32com.client.DispatchEx('Excel.Application')
    excel.Visible=False
    excel.DisplayAlerts=False
    book=None
    try:
        excel.Workbooks.OpenText(Filename=str(csv_path),Origin=65001,StartRow=1,DataType=1,TextQualifier=1,ConsecutiveDelimiter=False,Tab=False,Semicolon=False,Comma=True,Space=False,Other=False,FieldInfo=tuple((i+1,2) for i in range(len(expected[0]))))
        book=excel.ActiveWorkbook
        sheet=book.Worksheets(1)
        actual=sheet.UsedRange.Value2
        require(len(actual)==len(expected),'Excel imported row count changed')
        numeric_cells=0
        for i,row in enumerate(expected):
            for j,value in enumerate(row):
                cell=sheet.Cells(i+1,j+1)
                require(not cell.HasFormula,'Excel interpreted a CSV cell as a formula')
                observed=actual[i][j]
                if isinstance(observed,(int,float)):
                    numeric_cells+=1
                    require(Decimal(str(observed))==Decimal(value),'Excel numeric value differs from UTF8 CSV')
                else:
                    require(('' if observed is None else str(observed))==value,'Excel text value differs from UTF8 CSV')
        report['excel']={'version':str(excel.Version),'rows':len(actual)-1,'columns':len(expected[0]),'all_cells_match':True,'numeric_cells_compared_as_decimal':numeric_cells,'no_formulas':True,'method':'Native Excel COM OpenText UTF8 comma; Excel infers numeric cells for .csv despite FieldInfo. Exact decimal/text comparisons; not physical UI inspection'}
    finally:
        if book is not None:book.Close(SaveChanges=False)
        excel.Quit()
    report['verified']=True
    report['verified_at']=datetime.now(BEIJING).isoformat()
    (output/'browser-office-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))

if __name__=='__main__':main()
