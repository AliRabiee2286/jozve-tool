"""Read-only page/field comparison against the isolated ui-step7 outputs."""
import hashlib,json,sys
import numpy as np
import pymupdf as fitz
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from run_corpus import render_hashes


def run():
    olddir=ROOT/'cache/q8_ui_step7/output';newdir=ROOT/'output/corpus'
    old={i['files'][0]:i for i in json.loads((olddir/'report.json').read_text(encoding='utf-8'))['items']}
    new={i['files'][0]:i for i in json.loads((newdir/'report.json').read_text(encoding='utf-8'))['items']}
    assert set(old)==set(new)
    result=[]
    for source,item in new.items():
        previous=old[source]
        fields={key:{'old':previous.get('cover',{}).get('fields',{}).get(key,{}).get('value'),
                     'new':item.get('cover',{}).get('fields',{}).get(key,{}).get('value')}
                for key in ('teacher','course','chapter','topic')}
        fields={key:values for key,values in fields.items() if values['old']!=values['new']}
        entry={'source':source,'old_status':previous['status_code'],'new_status':item['status_code'],'fields':fields}
        if previous['status_code']!='BLOCKED' and item['status_code']!='BLOCKED':
            before=render_hashes(olddir/previous['output']);after=render_hashes(newdir/item['output'])
            changed=[i+1 for i in range(max(len(before),len(after))) if i>=len(before) or i>=len(after) or before[i]!=after[i]]
            outside=0
            if fields and changed==[1]:
                images=[];mask=np.zeros((before[0]['height'],before[0]['width']),dtype=bool)
                for directory,record in ((olddir,previous),(newdir,item)):
                    with fitz.open(directory/record['output']) as doc:
                        pix=doc[0].get_pixmap(dpi=72,alpha=False)
                        images.append(np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n))
                    for field in record['cover']['fields'].values():
                        x0,y0,x1,y1=fitz.Rect(field['bbox']).irect
                        mask[y0:y1,x0:x1]=True
                outside=int(np.any(images[0]!=images[1],axis=2)[~mask].sum())
            entry['cover_changed_pixels_outside_fields']=outside
            entry.update(old_output=previous['output'],new_output=item['output'],old_pages=before,new_pages=after,
                         changed_pages=changed,expected_cover_change=bool(fields) and changed==[1] and outside==0,
                         unexpected=bool(changed) and not (bool(fields) and changed==[1] and outside==0))
        else:entry['unexpected']=item['status_code']=='BLOCKED' and previous['status_code']!='BLOCKED'
        result.append(entry)
    proof={'base_commit':'4e61cb6dd496e5044d0e60ff605920f2a38b2c7c','dpi':72,'files':result,
           'new_blocked':sum(r['new_status']=='BLOCKED' and r['old_status']!='BLOCKED' for r in result),
           'unexpected':sum(r['unexpected'] for r in result)}
    destination=ROOT/'debug/qa_e2e/base_comparison.json'
    destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    text='# مقایسهٔ Q8 با ui-step7\n\nکامیت پایه: `'+proof['base_commit']+'`؛ هش SHA-256 رندر RGB در ۷۲ dpi.\n\n'
    text+='| ورودی | وضعیت قدیم / جدید | صفحه‌های متفاوت | تغییر فیلد سیلابس |\n|---|---|---|---|\n'
    for r in result:
        text+='| '+r['source']+' | '+r['old_status']+' / '+r['new_status']+' | '+str(r.get('changed_pages','unavailable'))+' | '+', '.join(r['fields'])+' |\n'
    text+='\n## متن‌های تغییرکرده؛ قدیم ← جدید\n\n'
    for r in result:
        if not r['fields']:continue
        text+='### '+r['source']+'\n\n'
        for key,values in r['fields'].items():
            text+='- '+key+': **قدیم:** '+str(values['old'])+' ← **جدید:** '+str(values['new'])+'\n'
        text+='\n'
    (ROOT/'docs/QA_Q8_BASE_COMPARISON.md').write_text(text.rstrip()+'\n',encoding='utf-8')
    print(json.dumps({'files':len(result),'new_blocked':proof['new_blocked'],'unexpected':proof['unexpected'],
                     'changed_covers':sum(r.get('expected_cover_change',False) for r in result)}))
    assert proof['unexpected']==0 and proof['new_blocked']==0, 'Unexpected regression: inspect saved comparison'

if __name__=='__main__':run()
