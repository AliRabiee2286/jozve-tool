"""Compare legacy-consumed syllabus sheets without changing workbooks or baselines."""
import json
import argparse
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from syllabus import Syllabus, load_config, discover_assets
from naamak import resolve_details


def sheet_records(syllabus):
    sheets={sheet:{} for sheet in syllabus.column_map}
    for index in (syllabus._index,syllabus._fallback_index):
        for key,rows in index.items():
            for row in rows:
                sheet=row['record']['sheet']
                sheets[sheet].setdefault(key,[]).append(row)
    return sheets


def compare_rows(old,new,fields):
    changes={};ambiguous={}
    for key in sorted(old.keys() & new.keys()):
        before=[{field:r['record'][field] for field in fields} for r in old[key]]
        after=[{field:r['record'][field] for field in fields} for r in new[key]]
        if len(before)!=1 or len(after)!=1:
            ambiguous[key]={'before':old[key],'after':new[key]}
        elif before!=after:
            changes[key]={'before':old[key],'after':new[key],
                          'fields':[f for f in fields if before[0][f]!=after[0][f]]}
    return {'added':{k:new[k] for k in sorted(new.keys()-old.keys())},
            'removed':{k:old[k] for k in sorted(old.keys()-new.keys())},
            'changed':changes,'ambiguous':ambiguous}


def lookup(syllabus,path,fields):
    try:
        match=resolve_details(path.stem,syllabus)
        row=syllabus.find(match['namak'])
        return {'status':'matched','namak':match['namak'],
                'fields':{field:row[field] for field in fields}}
    except (LookupError,ValueError) as exc:
        return {'status':'blocked','error':str(exc),'type':type(exc).__name__}


def compare_workbooks(old_path,new_path,cfg,inputs):
    old=Syllabus.from_workbook(old_path,cfg);new=Syllabus.from_workbook(new_path,cfg)
    before=sheet_records(old);after=sheet_records(new);fields=cfg['cover']['fields']
    reports={sheet:compare_rows(before.get(sheet,{}),after.get(sheet,{}),fields)
             for sheet in sorted(before.keys()|after.keys())}
    inputs_report=[]
    for path in inputs:
        a=lookup(old,path,fields);b=lookup(new,path,fields)
        changed=a['fields']!=b['fields'] if a['status']==b['status']=='matched' else None
        inputs_report.append({'input':path.name,'before':a,'after':b,'cover_fields_changed':changed})
    totals={key:sum(len(sheet[key]) for sheet in reports.values())
            for key in ('added','removed','changed','ambiguous')}
    return {'sheets':reports,'totals':totals,'inputs':inputs_report,
            'comparison':'trimmed display fields as consumed by current Syllabus; normalized namak; duplicates reported without selecting a row'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-ref',default='HEAD',help='Git revision holding the previous workbook')
    args=parser.parse_args()
    cfg=load_config(ROOT/'config.yaml');assets=discover_assets(cfg,ROOT)
    source=assets['syllabus'].relative_to(ROOT).as_posix()
    revision=subprocess.run(['git','rev-parse','--verify',args.base_ref+'^{commit}'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    data=subprocess.run(['git','show',revision+':'+source],cwd=ROOT,capture_output=True,check=True).stdout
    old=ROOT/'cache/q1_previous_syllabus.xlsx';old.write_bytes(data)
    inputs=sorted((ROOT/cfg['paths']['input']).glob('*.pdf'))
    report=compare_workbooks(old,assets['syllabus'],cfg,inputs)
    report['source_revision']=revision
    report['source_path']=source
    target=ROOT/'cache/q1_syllabus_diff.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'totals':report['totals'],'inputs':[{'input':v['input'],'changed':v['cover_fields_changed'],'before':v['before']['status'],'after':v['after']['status']} for v in report['inputs']]},ensure_ascii=False))
