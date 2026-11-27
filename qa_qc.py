"""Blocking QC of reopened QA PDFs, independent of publication."""
from collections import Counter
from pathlib import Path
import hashlib
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config, discover_assets, is_empty_value
from naamak import to_output_name
from pages import raster, number_candidates
from qc import image_signature
from frame import QAFrame
from qa_pages import frame_coverage
from qa_pipeline import assemble_qa


def glyphs(page, excluded=()):
    return Counter((c[0],c[1]) for s in page.get_texttrace() for c in s['chars']
                   if not any(fitz.Rect(box).contains(fitz.Point(c[2])) for box in excluded))


def check_qa_pdf(path,source,record,cover_report,pages_report,config_path=DEFAULT_CONFIG,output_suffix=''):
    cfg=load_config(config_path);checks={};details=[]
    def check(name,passed,detail=None):
        checks[name]=bool(passed)
        if detail is not None:details.append({'check':name,'detail':detail})
    try:
        with fitz.open(path) as doc:
            check('باز شدن PDF',not doc.needs_pass)
            check('تعداد صفحات',len(doc)==len(source)+1)
            check('نام فایل',Path(path).name==to_output_name(record['namak'],config_path,suffix=output_suffix))
            entries=pages_report.get('pages',[])
            check('تعداد شواهد صفحات',len(entries)==len(source))
            if doc.needs_pass or len(doc)!=len(source)+1 or len(entries)!=len(source):raise ValueError('QA_QC_INCOMPLETE_INPUT')
            expected,cr,pr=assemble_qa(source,record,config_path)
            with expected:
                front=doc[0];dpi=cfg['qa']['cover']['qc_dpi'];fields=cfg['qa']['cover']['fields']
                actual=raster(front,dpi);reference=raster(expected[0],dpi);same=actual.shape==reference.shape
                check('اندازه و جهت فرست‌پیج',front.rect==expected[0].rect and front.rotation==0)
                mask=np.zeros(reference.shape[:2],dtype=bool);field_equal=True
                for key in fields:
                    info=cover_report.get('fields',{}).get(key,{})
                    x0,y0,x1,y1=(fitz.Rect(cr['fields'][key]['region'])*(dpi/72)).irect
                    mask[y0:y1,x0:x1]=True
                    field_equal &= (info.get('value')==record[key] and
                        bool(info.get('empty'))==is_empty_value(record[key]) and same and
                        np.array_equal(actual[y0:y1,x0:x1],reference[y0:y1,x0:x1]))
                check('سه مقدار دقیق',field_equal and not all(is_empty_value(record[k]) for k in fields))
                check('نبود استاد و متن اضافی',set(cover_report.get('fields',{}))==set(fields) and glyphs(front)==glyphs(expected[0]))
                check('تغییر فقط در سه ناحیه',same and np.array_equal(actual[~mask],reference[~mask]) and cr['pixel_qc']['outside_values']==0)
                check('فرست‌پیج برابر مرجع',same and np.array_equal(actual,reference))
                assets=discover_assets(cfg,Path(config_path).resolve().parent,roles=['font'])
                font_hash=hashlib.sha256(assets['font'].read_bytes()).digest()
                check('فونت Aria جاسازی‌شده',any(hashlib.sha256(doc.extract_font(f[0])[3]).digest()==font_hash for f in front.get_fonts(full=True)))
                frame=QAFrame(config_path)
                for i,(original,page,entry,reference_entry) in enumerate(zip(source,list(doc)[1:],entries,pr['pages']),1):
                    prefix=f'صفحه محتوا {i}: '
                    check(prefix+'اندازه و جهت و rotation',
                        (page.rect,page.cropbox,page.mediabox,page.rotation)==(original.rect,original.cropbox,original.mediabox,original.rotation))
                    check(prefix+'رندر محتوا',np.array_equal(raster(page,dpi),raster(expected[i],dpi)))
                    check(prefix+'نبود شماره متن',not number_candidates(page,{**cfg['pages'],'bottom_fraction':cfg['pages']['qc_bottom_fraction']}))
                    check(prefix+'متن حفظ‌شده',glyphs(page)==glyphs(expected[i]) and
                          glyphs(original,[r['bbox'] for r in reference_entry['removed']])<=glyphs(page))
                    check(prefix+'تصاویر حفظ‌شده',image_signature(doc,page)==image_signature(source,original))
                    pieces=frame.placements(page.rect);drawings=page.get_drawings()[-len(pieces):]
                    valid=len(drawings)==len(pieces)
                    for drawn,part in zip(drawings,pieces):
                        valid &= drawn['type']=='s' and len(drawn['items'])==1 and drawn['items'][0][0]=='l'
                        if valid:
                            _,a,b=drawn['items'][0]
                            valid &= all(abs(x-y)<=frame.tolerance for p,q in zip((a*page.rotation_matrix,b*page.rotation_matrix),(part['a'],part['b'])) for x,y in zip(p,q))
                            valid &= abs(drawn['width']-part['width'])<=frame.tolerance and np.allclose(drawn['color'],part['color'],atol=1e-6)
                    check(prefix+'قاب معتبر',valid)
                    streams=page.get_contents();count=entry.get('frame_stream_count',0)
                    structure=count==len(pieces) and len(streams)==entry.get('content_stream_count',-1)+count
                    check(prefix+'ساختار لایه قاب',structure)
                    if structure:
                        doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in streams[:-count])+']')
                        page=doc.reload_page(page)
                        coverage=frame_coverage(page,frame,cfg['pages'])
                        check(prefix+'جوهر زیر قاب صفر',not any(v['meaningful_ink_pixels'] for v in coverage),coverage)
                    else:check(prefix+'جوهر زیر قاب صفر',False)
    except Exception as exc:check('خطای کنترل کیفیت',False,str(exc))
    blocking=set(cfg['qc_qa']['blocking'])
    failed=[k for k,v in checks.items() if not v]
    fatal=[k for k in failed if k.split(': ',1)[-1] in blocking]
    return {'passed':not fatal,'checks':checks,'details':details,'blocking_failed':fatal,
            'advisory_failed':[k for k in failed if k not in fatal]}
