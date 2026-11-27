"""Scan configured display-field columns across every workbook sheet, read-only."""
import json
import sys
from pathlib import Path
import openpyxl
import pymupdf as fitz
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from formula import render_formula_html,FormulaGlyphError,FormulaSyntaxError
from syllabus import load_config,discover_assets,normalize_key


def scan_workbook():
    cfg=load_config(ROOT/'config.yaml');assets=discover_assets(cfg,ROOT)
    font=fitz.Font(fontfile=str(assets['font']));settings=cfg['qa']['formula']
    aliases={normalize_key(alias):field for field in cfg['qa']['cover']['fields'] for alias in cfg['headers'][field]}
    report={'sheets':[],'formula_cells':[],'errors':[],'plain_cells':0}
    wb=openpyxl.load_workbook(assets['syllabus'],read_only=True,data_only=True)
    try:
        for ws in wb:
            columns={};header=None
            for row in ws.iter_rows(min_row=1,max_row=cfg['header_scan_rows']):
                found={cell.column:aliases[normalize_key(cell.value)] for cell in row
                       if isinstance(cell.value,str) and normalize_key(cell.value) in aliases}
                if found:columns=found;header=row[0].row;break
            detail={'sheet':ws.title,'header_row':header,'columns':columns,'text_cells':0}
            if header:
                for row in ws.iter_rows(min_row=header+1):
                    for cell in row:
                        if cell.column not in columns or not isinstance(cell.value,str):continue
                        detail['text_cells']+=1
                        item={'sheet':ws.title,'cell':cell.coordinate,'field':columns[cell.column],'text':cell.value}
                        try:
                            html,info=render_formula_html(cell.value,settings=settings,font=font)
                            if html is None:report['plain_cells']+=1
                            else:report['formula_cells'].append(dict(item,html=html,report=info))
                        except (FormulaGlyphError,FormulaSyntaxError) as exc:
                            report['errors'].append(dict(item,error=str(exc),code=exc.code))
            report['sheets'].append(detail)
    finally:wb.close()
    return report


if __name__=='__main__':
    result=scan_workbook()
    (ROOT/'cache/q4_formula_scan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'sheets':len(result['sheets']),'plain_cells':result['plain_cells'],
                      'formula_cells':result['formula_cells'],'errors':result['errors']},ensure_ascii=False))
    raise SystemExit(bool(result['errors']))
