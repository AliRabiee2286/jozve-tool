"""Independent edge fixtures: source files live only under tests/data/step5."""
import json
from pathlib import Path
import subprocess
import sys
import warnings
import uuid
import math
import numpy as np
import openpyxl
import pymupdf as fitz
import pytest
import main as app
from syllabus import Syllabus, load_config
from naamak import to_output_name
from cover import build_cover, TextFitError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tests/data/step5'
OUT = ROOT / 'output/step5_edges'


def make_source(path, geometries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as doc:
        for i, (w, h, rotation) in enumerate(geometries):
            p = doc.new_page(width=w, height=h)
            p.insert_text((100, 120), f'Independent content {i+1}', fontsize=16)
            p.draw_rect(fitz.Rect(90, 150, 230, 230), color=(0, 0, 1), fill=(1, .8, .8))
            p.set_rotation(rotation)
        doc.save(path)


@pytest.fixture(scope='module')
def context():
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        syll = Syllabus()
    return load_config(), syll


def job(context, path, tag, syllabus=None):
    cfg, syll = context
    out = OUT / tag
    out.mkdir(exist_ok=True)
    result = app.process_job([path], None, syllabus or syll, cfg, out, set())
    (out / 'evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result, out


@pytest.mark.parametrize('tag,geometry', [
    ('single', [(595, 842, 0)]),
    ('mixed', [(595, 842, 0), (960, 540, 0), (611, 793, 0)]),
    ('rotation90', [(595, 842, 90)]),
    ('size611', [(611, 793, 0)]),
    ('size595', [(595, 842, 0)]),
    ('size960', [(960, 540, 0)]),
])
def test_page_geometry(context, tag, geometry):
    path = DATA / tag / 'physics_thermo_9.pdf'
    make_source(path, geometry)
    result, out = job(context, path, tag)
    assert result['status'] == 'موفق', result.get('error', result)
    assert all(result['qc']['checks'].values())
    with fitz.open(path) as source, fitz.open(out / result['output']) as target:
        assert len(target) == len(source) + 1
        assert (target[0].rect.width > target[0].rect.height) == (source[0].rect.width > source[0].rect.height)
        for p, q in zip(source, list(target)[1:]):
            assert p.rect == q.rect and p.rotation == q.rotation
            assert p.mediabox == q.mediabox and p.cropbox == q.cropbox
            assert q.get_text().replace('BALATAR.GROUP\n', '') == p.get_text()


def test_dirty_literal_x_matches_synthetic_syllabus(context):
    cfg, _ = context
    book = openpyxl.Workbook(); sheet = book.active
    sheet.title = next(iter(cfg['sheet_to_template']))
    sheet.append(['نامک', 'استاد', 'درس', 'فصل', 'مبحث'])
    sheet.append(['x', 'استاد آزمایشی', 'درس آزمایشی', 'فصل آزمایشی', 'مبحث آزمایشی'])
    path = DATA / 'synthetic.xlsx'; book.save(path); book.close()
    local = dict(cfg, sheet_to_template={sheet.title: cfg['sheet_to_template'][sheet.title]}, header_overrides={})
    syll = Syllabus.from_workbook(path, local)
    pdf = DATA / 'dirty' / 'x (1) (1).pdf'; make_source(pdf, [(595, 842, 0)])
    result, out = job(context, pdf, 'dirty', syll)
    assert result['status'] == 'موفق', result
    assert result['namak'] == 'x' and all(result['qc']['checks'].values())
    assert (out / to_output_name('x')).is_file()


@pytest.mark.parametrize('kind', ['unknown', 'corrupt', 'encrypted'])
def test_invalid_inputs_rejected(context, kind):
    path = DATA / kind / ('step5_nonexistent.pdf' if kind == 'unknown' else 'physics_thermo_9.pdf')
    make_source(path, [(595, 842, 0)])
    if kind == 'corrupt': path.write_bytes(b'%PDF-1.7\ninvalid test fixture')
    if kind == 'encrypted':
        with fitz.open(path) as doc:
            payload = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=uuid.uuid4().hex, user_pw=uuid.uuid4().hex)
        path.write_bytes(payload)
    result, out = job(context, path, kind)
    assert result['status'] == 'خطا' and result.get('error')
    assert not list(out.glob('*.pdf'))
    if kind == 'unknown': assert 'نامک در سیلابس پیدا نشد' in result['error']
    if kind == 'encrypted': assert 'رمزدار' in result['error']


def test_empty_input(context):
    empty = DATA / 'empty'; empty.mkdir(exist_ok=True)
    out = OUT / 'empty'
    run = subprocess.run([sys.executable, str(ROOT/'main.py'), '--input', str(empty), '--output', str(out)], capture_output=True, timeout=120)
    assert run.returncode == 1
    report = json.loads((out/'report.json').read_text(encoding='utf-8'))
    assert 'وجود ندارد' in report['items'][0]['error']
    assert not list(out.glob('*.pdf'))


def test_two_runs_overwrite(context):
    path = DATA/'repeat'/'physics_thermo_9.pdf'; make_source(path, [(595,842,0)])
    first, out = job(context, path, 'repeat')
    assert first['status'] == 'موفق'
    target=out/first['output']; stamp=target.stat().st_mtime_ns
    second, _ = job(context, path, 'repeat')
    assert second['status']=='موفق' and all(second['qc']['checks'].values())
    assert target.stat().st_mtime_ns > stamp
    assert len(list(out.glob('*.pdf'))) == 1


@pytest.mark.parametrize('namak,sheet,index', [('shimi_alee_7','شیمی',14),('ECONO GO P 7','اقتصاد',12)])
def test_other_subjects(context, namak, sheet,index):
    # Independent, user-approved sheet/template ordinals from the visual inspection.
    assert context[1].find(namak)['template_index']==index
    path=DATA/sheet/(namak+'.pdf'); make_source(path, [(595,842,0)])
    result, _=job(context,path,sheet)
    assert result['status']=='موفق',result
    assert result['sheet']==sheet and all(result['qc']['checks'].values())
    if sheet=='اقتصاد': assert any('اطلاعات عمومی' in w for w in context[1].warnings)


@pytest.mark.parametrize('orientation',['portrait','landscape'])
def test_topic_over_100_characters(context,orientation):
    cfg,syll=context; record=syll.find('physics_thermo_9')
    values={f:record[f] for f in cfg['cover']['fields']}
    values['topic']='بررسی مفاهیم بنیادی و کاربردهای علمی در حل مسئله و تحلیل نتایج آزمایش برای شناخت دقیق پدیده‌ها و ارتباط میان کمیت‌های فیزیکی'
    assert len(values['topic'])>100
    doc, report=build_cover(record['template_index'],orientation,values)
    try:
        assert report['fields']['topic']['value']==values['topic']
        assert report['fields']['topic']['line_count']<=4
        dpi=cfg['cover']['qc_dpi']
        def pixels(page):
            pix=page.get_pixmap(dpi=dpi,alpha=False)
            return np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,3)
        generated=pixels(doc[0])
        with fitz.open(syll.assets['template']) as templates:
            blank=pixels(templates[report['template_page']-1])
        changed=np.any(generated!=blank,axis=2)
        mask=np.zeros(changed.shape,dtype=bool)
        for field in report['fields'].values():
            assert fitz.Rect(field['bbox']).contains(fitz.Rect(field['ink_bbox']))
            assert field['scale'] >= cfg['cover']['min_scale']
            x0,y0,x1,y1=field['bbox']
            x0,y0=math.floor(x0*dpi/72),math.floor(y0*dpi/72)
            x1,y1=math.ceil(x1*dpi/72),math.ceil(y1*dpi/72)
            mask[y0:y1,x0:x1]=True
            assert changed[y0:y1,x0:x1].any()
        assert not changed[~mask].any()
        doc.save(OUT/f'long_topic_{orientation}.pdf')
        (OUT/f'long_topic_{orientation}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally: doc.close()


def test_unfittable_topic_is_rejected_without_truncation(context):
    cfg,syll=context;record=syll.find('physics_thermo_9')
    values={f:record[f] for f in cfg['cover']['fields']}
    values['topic']='مبحث طولانی و غیرقابل جایگذاری ' * 100
    with pytest.raises(TextFitError):
        build_cover(record['template_index'],'portrait',values)


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_rotated_footer_number_and_offset_crop(context,rotation):
    path=DATA/f'crop{rotation}'/'physics_thermo_9.pdf';path.parent.mkdir(exist_ok=True)
    with fitz.open() as doc:
        page=doc.new_page(width=700,height=900)
        page.set_cropbox(fitz.Rect(30,40,650,850))
        page.set_rotation(rotation)
        # Write into displayed bottom, translating the coordinate back to page space.
        point=fitz.Point(80,page.rect.height-12)*page.derotation_matrix
        page.insert_text(point,'Page 7',fontsize=8,rotate=rotation)
        point=fitz.Point(100,150)*page.derotation_matrix
        page.insert_text(point,'Content stays',fontsize=12,rotate=rotation)
        doc.save(path)
    result,out=job(context,path,f'crop{rotation}')
    assert result['status']=='موفق',result
    assert all(result['qc']['checks'].values())
    with fitz.open(out/result['output']) as doc:
        assert 'Page' not in doc[1].get_text()
        assert 'Content stays' in doc[1].get_text()
