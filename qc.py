"""QC of reopened PDFs. Cover content is checked exclusively through rendering."""
from pathlib import Path
import hashlib
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config, discover_assets
from naamak import to_output_name
from cover import effective_orientation, select_template, detect_regions
from pages import raster, number_candidates, coverage


def image_signature(document,page):
    # Redaction can add resource aliases to an existing image (24 resources become
    # 38 aliases in the economy input). Hash image bytes AND every displayed use;
    # aliases are not new images. Losing even one repeated use changes placements.
    objects=sorted({hashlib.sha256(document.extract_image(x[0])['image']).hexdigest() for x in page.get_images()})
    # A fresh TextPage avoids Page.get_image_info's stale cache after mutations.
    info=page.get_textpage(flags=fitz.TEXT_PRESERVE_IMAGES).extractIMGINFO(hashes=True)
    uses=sorted((x['digest'].hex(),x['width'],x['height']) for x in info)
    return objects,uses


def check_pdf(path, source, record, cover_report, pages_report, expected_cover,
              config_path=DEFAULT_CONFIG, output_name=None, expected_content_renders=None):
    cfg=load_config(config_path); assets=discover_assets(cfg,Path(config_path).resolve().parent)
    checks={}; details=[]
    def check(name, passed, detail=None):
        checks[name]=bool(passed)
        if detail is not None: details.append({'check':name,'detail':detail})
    try:
        with fitz.open(path) as doc:
            check('باز شدن PDF',not doc.needs_pass)
            check('نام فایل',(output_name or Path(path).name)==to_output_name(record['namak'],config_path))
            check('تعداد صفحات',len(doc)==len(source)+1)
            # A truncated zip would otherwise silently skip content-page QC.
            evidence=pages_report.get('pages',[])
            evidence_complete=len(evidence)==len(source)
            check('تعداد شواهد صفحات محتوا',evidence_complete)
            renders_complete=expected_content_renders is None or len(expected_content_renders)==len(source)
            check('تعداد رندرهای مرجع محتوا',renders_complete)
            if doc.needs_pass or len(doc)!=len(source)+1 or not evidence_complete or not renders_complete:
                return {'passed':False,'checks':checks,'details':details}
            front=doc[0]; dpi=cfg['cover']['qc_dpi']
            check('جهت فرست‌پیج',effective_orientation(front)==effective_orientation(source[0]))
            font_hash=hashlib.sha256(assets['font'].read_bytes()).digest()
            fonts=[doc.extract_font(f[0]) for f in front.get_fonts(full=True)]
            check('فونت Aria Regular جاسازی‌شده',any(f[3] and hashlib.sha256(f[3]).digest()==font_hash for f in fonts))
            fields=cfg['cover']['fields']
            check('چهار مقدار دقیق و ناتهی',all(isinstance(record[f],str) and record[f].strip() and
                  cover_report['fields'][f]['value']==record[f] for f in fields))
            with fitz.open(assets['template']) as templates:
                blank=templates[select_template(templates,record['template_index'],effective_orientation(source[0]))]
                regions,_,_=detect_regions(blank,cfg['cover'])
                a,b=raster(front,dpi),raster(blank,dpi)
                same=a.shape==b.shape
                counts={};outside=None
                if same:
                    changed=np.any(a!=b,axis=2); mask=np.zeros(changed.shape,bool)
                    for key,rect in regions.items():
                        x0,y0,x1,y1=(rect*(dpi/72)).irect
                        mask[y0:y1,x0:x1]=True; counts[key]=int(changed[y0:y1,x0:x1].sum())
                    outside=int(changed[~mask].sum())
                check('رندر فرست‌پیج فقط در چهار ناحیه',same and outside==0 and all(counts.values()),
                      {'outside_pixels':outside,'field_pixels':counts})
                reference=raster(expected_cover[0],dpi)
                check('فرست‌پیج بدون بوردر و برابر مرجع نوشتن',a.shape==reference.shape and np.array_equal(a,reference))
            for i,(original,page,entry) in enumerate(zip(source,list(doc)[1:],pages_report['pages']),1):
                prefix=f'صفحه محتوا {i}: '
                if expected_content_renders is not None:
                    actual_render=raster(page,cfg['pages']['diagnostic_dpi'])
                    reference_render=expected_content_renders[i-1]
                    same_shape=actual_render.shape==reference_render.shape
                    different=int(np.any(actual_render!=reference_render,axis=2).sum()) if same_shape else None
                    check(prefix+'رندر پس از مونتاژ',same_shape and different==0,
                          {'different_pixels':different,'same_shape':same_shape})
                check(prefix+'اندازه و جهت و rotation',original.rect==page.rect and original.rotation==page.rotation and
                      original.cropbox==page.cropbox and original.mediabox==page.mediabox)
                check(prefix+'BALATAR.GROUP',cfg['border']['retained_text'] in page.get_text())
                check(prefix+'نبود شماره متن',not number_candidates(page,
                      {**cfg['pages'],'bottom_fraction':cfg['pages']['qc_bottom_fraction']}))
                expected=original.get_text()
                for removed in entry['removed']: expected=expected.replace(removed['text']+'\n','')
                actual='\n'.join(s for s in page.get_text().splitlines() if s.strip()!=cfg['border']['retained_text'])
                check(prefix+'متن حفظ شده',actual==expected.rstrip('\n'))
                check(prefix+'هش تصاویر و تعداد کاربردها',image_signature(source,original)==image_signature(doc,page))
                # Work on the reopened in-memory document only; the saved PDF is untouched.
                streams=page.get_contents(); count=entry['border_stream_count']
                valid=count==len(entry['pieces']) and len(streams)==entry['content_stream_count']+count
                check(prefix+'ساختار لایه بوردر',valid)
                if not valid: continue
                doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in streams[:-count])+']')
                page=doc.reload_page(page)
                ink=coverage(page,entry['pieces'],cfg['pages'])
                check(prefix+'جوهر زیر نوارها صفر',all(r['meaningful_ink_pixels']==0 for r in ink),ink)
    except Exception as exc:
        check('خطای کنترل کیفیت',False,str(exc))
    return {'passed':bool(checks) and all(checks.values()),'checks':checks,'details':details}
