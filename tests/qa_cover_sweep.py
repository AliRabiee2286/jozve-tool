"""Reproducible native QA cover sweep and local visual evidence."""
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from syllabus import Syllabus,is_empty_value
from qa_cover import QACoverBuilder


def records(syllabus):
    return [dict(item['record'],workbook_row=item['row']) for group in syllabus._index.values()
            for item in group if item['record'].get('kind') in syllabus.config['qa']['kinds']]


def run_sweep(output=ROOT/'cache/qa_cover_sweep.json',artifacts=False):
    syllabus=Syllabus(ROOT/'config.yaml');rows=records(syllabus)
    results=[];started=time.perf_counter()
    with QACoverBuilder(ROOT/'config.yaml') as builder:
        fields=builder.settings['fields']
        longest=max(rows,key=lambda r:max(len(str(r[f])) if not is_empty_value(r[f]) else 0 for f in fields))
        special={'long':longest}
        special['empty']=next(r for r in rows if is_empty_value(r[fields[-1]]) and not all(is_empty_value(r[f]) for f in fields))
        marker=builder.cfg['qa']['formula']['superscript_marker']
        special['formula']=next(r for r in rows if any(isinstance(r[f],str) and marker in r[f] for f in fields))
        seen=set();visuals=[]
        if artifacts:(ROOT/'debug/qa_cover').mkdir(exist_ok=True)
        for index,row in enumerate(rows,1):
            values={f:row[f] for f in fields}
            item={'namak':row['namak'],'kind':row['kind'],'sheet':row['sheet'],'row':row['workbook_row'],
                  'lengths':{f:len(str(row[f])) if not is_empty_value(row[f]) else 0 for f in fields},'empty_fields':[f for f in fields if is_empty_value(row[f])]}
            try:
                doc,report=builder.build(row['kind'],row['template_index'],values,'native')
                try:
                    item.update(status='ok',scales={f:r.get('scale') for f,r in report['fields'].items()},pixel_qc=report['pixel_qc'])
                    names=[]
                    key=(row['kind'],row['template_index'])
                    if key not in seen:names.append('template_'+str(report['template_page']));seen.add(key)
                    names.extend(name for name,r in special.items() if r is row)
                    if artifacts:
                        for name in names:
                            base=ROOT/'debug/qa_cover'/name
                            doc.save(str(base)+'.pdf')
                            doc[0].get_pixmap(dpi=builder.settings['qc_dpi']).save(str(base)+'.png')
                            base.with_suffix('.json').write_text(json.dumps(dict(report,namak=row['namak']),ensure_ascii=False,indent=2),encoding='utf-8')
                            visuals.append(name)
                finally:doc.close()
            except Exception as exc:
                item.update(status='empty' if all(is_empty_value(v) for v in values.values()) else 'error',
                            error_type=type(exc).__name__,error=str(exc))
            results.append(item)
            if index%100==0 or index==len(rows):
                report={'complete':index==len(rows),'processed':index,'total':len(rows),'seconds':time.perf_counter()-started,
                        'max_length':max(max(v['lengths'].values()) for v in results),'results':results,'visuals':visuals,
                        'ok':sum(v['status']=='ok' for v in results),'empty':sum(v['status']=='empty' for v in results),
                        'errors':sum(v['status']=='error' for v in results)}
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print('Sweep',index,'/',len(rows),'ok',report['ok'],'empty',report['empty'],'errors',report['errors'],'seconds',round(report['seconds'],1),flush=True)
    return report


if __name__=='__main__':
    result=run_sweep(artifacts=True)
    raise SystemExit(bool(result['errors']))
