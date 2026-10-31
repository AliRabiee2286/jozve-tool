"""Cover acceptance: pixels, HTML layout geometry, font streams, and independent XLSX values.
Never decode generated PDF text for QC.
"""
import hashlib
import json
import math
from pathlib import Path
import warnings
import numpy as np
from PIL import Image
import openpyxl
import pymupdf as fitz
import pytest
from syllabus import Syllabus, load_config, discover_assets
from naamak import resolve, to_output_name
from cover import build_cover, effective_orientation, select_template, CoverError, TextFitError

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('teacher', 'course', 'chapter', 'topic')


def raster(page, dpi=150):
    p = page.get_pixmap(dpi=dpi, alpha=False)
    return np.frombuffer(p.samples, dtype=np.uint8).reshape(p.height, p.width, p.n).copy()


def pixels(box, shape, dpi=150):
    x0,y0,x1,y1=box
    return (max(0,math.floor(x0*dpi/72)),max(0,math.floor(y0*dpi/72)),
            min(shape[1],math.ceil(x1*dpi/72)),min(shape[0],math.ceil(y1*dpi/72)))


def bounds(image, box, threshold=245, dpi=150):
    x0,y0,x1,y1=pixels(box,image.shape,dpi)
    ys,xs=np.nonzero(np.min(image[y0:y1,x0:x1,:3],axis=2)<threshold)
    if not len(xs):return None
    return [(xs.min()+x0)*72/dpi,(ys.min()+y0)*72/dpi,(xs.max()+x0+1)*72/dpi,(ys.max()+y0+1)*72/dpi]


@pytest.fixture(scope='module')
def data():
    cfg=load_config()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore');syll=Syllabus()
    wb=openpyxl.load_workbook(syll.workbook_path,data_only=True,read_only=True)
    rows={s:list(wb[s].iter_rows(values_only=True)) for s in cfg['sheet_to_template']}
    wb.close()
    return cfg,syll,rows


@pytest.fixture(scope='module')
def covers(data,tmp_path_factory):
    cfg,syll,rows=data
    result=[]
    saved_covers=tmp_path_factory.mktemp('saved_covers')
    for source in sorted((ROOT/cfg['paths']['input']).glob('*.pdf')):
        if 'input/'+source.name not in json.loads((ROOT/'tests/data/inspection_evidence.json').read_text(encoding='utf-8'))['source_hashes_before']:
            continue  # Historical four-sample visual baseline; six-file CLI acceptance is separate.
        name=resolve(source.name,syll);record=syll.find(name)
        # Independent known source coordinates B:F, not the implementation's returned values.
        match=[r for r in rows[record['sheet']] if len(r)>5 and r[1]==record['namak']]
        assert len(match)==1
        values={k:v.strip() if isinstance(v,str) else v for k,v in zip(FIELDS,match[0][2:6])}
        with fitz.open(source) as doc:orientation=effective_orientation(doc[0])
        doc,report=build_cover(record['template_index'],orientation,values)
        slug=name.replace(' ','_')
        saved=saved_covers/f'cover_{slug}.pdf'
        doc.save(saved,deflate=True)
        # QC the saved/reopened PDF, including catalog color management.
        reopened=fitz.open(saved)
        doc.close();doc=reopened
        generated=raster(doc[0]);Image.fromarray(generated).save(ROOT/f'debug/cover_{slug}.png')
        with fitz.open(syll.assets['template']) as templates:
            blank=raster(templates[report['template_page']-1])
        with fitz.open(ROOT/'samples'/to_output_name(name)) as sample:
            reference=raster(sample[0])
        assert reference.shape==generated.shape
        Image.fromarray(np.concatenate((generated,reference),axis=1)).save(ROOT/f'debug/cover_{slug}_vs_sample.png')
        changed=np.any(generated!=blank,axis=2)
        mask=np.zeros(changed.shape,dtype=bool)
        metrics={}
        for field in FIELDS:
            area=report['fields'][field]['bbox'];x0,y0,x1,y1=pixels(area,generated.shape)
            mask[y0:y1,x0:x1]=True
            ours=bounds(generated,area);theirs=bounds(reference,area)
            distance=math.dist([(ours[i]+ours[i+2])/2 for i in range(2)],[(theirs[i]+theirs[i+2])/2 for i in range(2)]) if ours and theirs else None
            metrics[field]={'ours_ink_bbox':ours,'sample_ink_bbox':theirs,'center_distance_pt':distance,
                            'different_pixels_percent':float(np.mean(np.any(generated[y0:y1,x0:x1]!=reference[y0:y1,x0:x1],axis=2))*100),
                            'changed_from_blank_pixels':int(changed[y0:y1,x0:x1].sum())}
        report.update(namak=name,metrics=metrics,outside_changed_pixels=int(changed[~mask].sum()),
                      page_different_percent=float(np.mean(np.any(generated!=reference,axis=2))*100))
        (ROOT/f'debug/cover_{slug}_qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        result.append((doc,report,values,blank,generated))
    yield result
    for doc,*_ in result:doc.close()


@pytest.mark.parametrize('i',range(4))
def test_four_acceptance(covers,data,i):
    doc,report,expected,blank,generated=covers[i]
    assert {k:v['value'] for k,v in report['fields'].items()}==expected
    assert len(doc)==1
    assert report['outside_changed_pixels']==0
    assert not doc[0].get_images()
    assert effective_orientation(doc[0])==report['orientation']
    for field,item in report['fields'].items():
        assert report['metrics'][field]['changed_from_blank_pixels']>0
        assert report['metrics'][field]['ours_ink_bbox'] is not None
        assert fitz.Rect(item['bbox']).contains(fitz.Rect(item['ink_bbox']))
        assert item['layout_height']<=fitz.Rect(item['bbox']).height
        assert 1<=item['line_count']<=item['max_lines']
        assert item['label_size']*.6<=item['font_size']<=item['label_size']
        assert item['font_embedded']


@pytest.mark.parametrize('field',FIELDS)
@pytest.mark.parametrize('orientation',['portrait','landscape'])
def test_longest(data,field,orientation):
    cfg,syll,rows=data
    # Find the actual longest trimmed cell over all configured sheets, independently.
    records=[]
    for sheet,rs in rows.items():
        columns=syll.column_map[sheet]
        for rownum,row in enumerate(rs,1):
            if rownum<=columns['header_row']:continue
            if not isinstance(row[columns['columns']['namak']-1],str):continue
            value=row[columns['columns'][field]-1]
            if isinstance(value,str) and value.strip():records.append((len(value.strip()),sheet,rownum,value.strip(),row))
    _,sheet,rownum,value,row=max(records,key=lambda x:x[0])
    columns=syll.column_map[sheet]['columns']
    # Stress payload combines the independently longest values of all four fields.
    values={}
    for k in FIELDS:
        pool=[]
        for sh,all_rows in rows.items():
            info=syll.column_map[sh]
            for rr in all_rows[info['header_row']:]:
                val=rr[info['columns'][k]-1]
                if isinstance(rr[info['columns']['namak']-1],str) and isinstance(val,str) and val.strip():
                    pool.append(val.strip())
        values[k]=max(pool,key=len)
    doc,report=build_cover(cfg['sheet_to_template'][sheet],orientation,values)
    try:
        item=report['fields'][field]
        assert item['value']==value
        assert 1<=item['line_count']<=item['max_lines']
        assert fitz.Rect(item['bbox']).contains(fitz.Rect(item['ink_bbox']))
        report.update(longest_field=field,sheet=sheet,row=rownum,length=len(value))
        (ROOT/f'debug/cover_longest_{field}_{orientation}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        doc[0].get_pixmap(dpi=150).save(ROOT/f'debug/cover_longest_{field}_{orientation}.png')
    finally:doc.close()


def test_template_selection_counts_and_rotation():
    d=fitz.open()
    d.new_page(width=200,height=300)
    d.new_page(width=400,height=200)
    p=d.new_page(width=200,height=300);p.set_rotation(90)
    assert select_template(d,2,'landscape')==2
    assert effective_orientation(p)=='landscape'
    for index,direction in [(2,'portrait'),(0,'portrait'),(1,'invalid')]:
        with pytest.raises(CoverError):select_template(d,index,direction)
    d.close()


def test_missing_template_and_overflow(data):
    cfg,syll,rows=data
    with pytest.raises(CoverError):build_cover(999,'portrait',dict.fromkeys(FIELDS,'متن'))
    values=dict.fromkeys(FIELDS,'متن');values['topic']='رسانه ' * 1000
    with pytest.raises(TextFitError):build_cover(next(iter(cfg['sheet_to_template'].values())),'portrait',values)


def test_sources_unchanged():
    evidence=json.loads((ROOT/'tests/data/inspection_evidence.json').read_text(encoding='utf-8'))
    for path,digest in evidence['source_hashes_before'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest


def test_all_template_geometries(data):
    from cover import detect_regions
    cfg,syll,_=data
    with fitz.open(syll.assets['template']) as templates:
        for page in templates:
            regions,sizes,frame=detect_regions(page,cfg['cover'])
            assert list(regions)==list(FIELDS)
            assert all(frame.contains(r) and r.width>0 and r.height>0 for r in regions.values())
            rects=list(regions.values())
            assert all(rects[i].y1<=rects[i+1].y0 for i in range(len(rects)-1))


def test_full_size_first_and_invalid_values(covers):
    for _,report,*_ in covers:
        for field in ('teacher','course','chapter'):
            item=report['fields'][field]
            assert item['scale']==1
    values=dict.fromkeys(FIELDS,'متن');values['teacher']=''
    with pytest.raises(TextFitError):build_cover(1,'portrait',values)
    with pytest.raises(CoverError):build_cover(1,'portrait',{})
