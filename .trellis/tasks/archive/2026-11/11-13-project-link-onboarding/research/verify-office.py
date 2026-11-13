"""Validate synthetic frozen CSVs in native Excel and render the HTML to A4 PDF."""
from __future__ import annotations
import argparse,csv,json,os,sys
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
SOURCE=next(p for p in Path(__file__).resolve().parents if (p / 'pyproject.toml').is_file() and (p / 'src/aha').is_dir())
RESEARCH=Path(__file__).resolve().parent
ROOT=Path(os.environ['AHA_PROJECT_LINK_ROOT'])
SHOTS=Path('C:/Users/djsyw/.codex/visualizations/2026/11/13/01a1d2b9-1dc4-7ef0-b130-8e2be6af3f48/aha-project-link')
SHOTS.mkdir(parents=True,exist_ok=True)
EDGE=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
sys.path.insert(0,str(SOURCE/'scripts'))
import verify_windows_artifact as artifact

def office(label):
    import win32com.client
    from playwright.sync_api import sync_playwright
    from pypdf import PdfReader
    import pymupdf

    material = ROOT / ("verify-" + label) / "material"
    manifest = json.loads((material / "导出信息.json").read_text(encoding="utf-8"))
    expected_cost = manifest["summary"]["total_cost_usd"]
    assert Decimal(expected_cost) == Decimal("0.570000003")
    result = {"verified":False,"material_sha256":artifact.digest(material/"evidence.zip"),
              "physical_office_input":False,"native_excel":[],"print":{}}
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        for filename in ("使用明细.csv","每日汇总.csv"):
            with (material/filename).open(encoding="utf-8-sig",newline="") as stream:
                expected = list(csv.reader(stream))
            excel.Workbooks.OpenText(Filename=str(material/filename),Origin=65001,StartRow=1,
                DataType=1,TextQualifier=1,ConsecutiveDelimiter=False,Tab=False,Semicolon=False,
                Comma=True,Space=False,Other=False,
                FieldInfo=tuple((i+1,2) for i in range(len(expected[0]))))
            book = excel.ActiveWorkbook
            try:
                sheet = book.Worksheets(1)
                sheet.Columns.AutoFit()
                actual = sheet.UsedRange.Value2
                assert len(actual) == len(expected)
                for i,row in enumerate(expected):
                    for j,value in enumerate(row):
                        cell = sheet.Cells(i+1,j+1)
                        assert not cell.HasFormula
                        observed = actual[i][j]
                        if isinstance(observed,(int,float)):
                            if len(value)==10 and value[4:5]=="-" and value[7:8]=="-":
                                assert cell.Value.date() == datetime.fromisoformat(value).date()
                                assert "#" not in cell.Text
                            else:
                                assert Decimal(str(observed)) == Decimal(value)
                        else:
                            assert ("" if observed is None else str(observed)) == value
                result["native_excel"].append({"file":filename,"rows":len(expected),"all_cells_checked":True})
            finally:
                book.Close(SaveChanges=False)
    finally:
        excel.Quit()
    pdf = material / "a4.pdf"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=EDGE,headless=True)
        try:
            page = browser.new_page(locale="zh-CN")
            page.goto((material/"费用说明.html").as_uri())
            assert expected_cost in page.locator("body").inner_text()
            page.pdf(path=str(pdf),format="A4",print_background=True,prefer_css_page_size=True)
        finally:
            browser.close()
    document = PdfReader(pdf)
    assert expected_cost in "\n".join(page.extract_text() for page in document.pages)
    sizes = [[float(page.mediabox.width),float(page.mediabox.height)] for page in document.pages]
    assert sizes and all(abs(w-595.28)<2 and abs(h-841.89)<2 for w,h in sizes)
    image = SHOTS / ("a4-"+label+".png")
    with pymupdf.open(pdf) as rendered:
        rendered[0].get_pixmap(matrix=pymupdf.Matrix(1.25,1.25)).save(image)
    result["print"]={"pages":len(sizes),"a4_page_sizes_pt":sizes,"precise_cost_preserved":True,
                     "pdf_sha256":artifact.digest(pdf),"first_page_rendered":image.name}
    result["verified"]=True
    return result


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--label',required=True);args=parser.parse_args()
 assert json.loads((ROOT/'task-ownership.json').read_text())['task']=='project-link-onboarding'
 result=office(args.label);result['label']=args.label
 (RESEARCH/('office-'+args.label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
