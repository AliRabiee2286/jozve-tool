"""Step 3: content preservation, calibrated vector caps, and visible rotation."""
import hashlib
import json
from pathlib import Path
import re
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz
import pytest
from syllabus import load_config, discover_assets
from border import clean_border, apply_border, placements
from pages import (process_pages, number_candidates, remove_numbers, raster,
                   _preserve_rendering_attributes, meaningful_ink, bake_annotations, fit_content)

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()


def text_without_numbers(text):
    # Independent acceptance expression: deliberately not the production helper.
    return '\n'.join(line for line in text.splitlines() if not re.fullmatch(
        r'\s*(?:\d+|(?:Page|صفحه)\s*[:：]?\s*\d+|New\s+Section\s+\d+(?:\s+Page\s+\d+)?)\s*',
        line, re.I) and line.strip() != 'BALATAR.GROUP')


def image_hashes(doc, page):
    return sorted(hashlib.sha256(doc.extract_image(item[0])['image']).hexdigest()
                  for item in page.get_images(full=True))


@pytest.fixture(scope='module')
def clean():
    path, evidence = clean_border()
    return path, evidence


@pytest.fixture(scope='module')
def processed(clean):
    debug = ROOT / CFG['paths']['debug']
    cache = ROOT / CFG['paths']['cache']
    records = []
    for src in sorted((ROOT / CFG['paths']['input']).glob('*.pdf')):
        doc, report = process_pages(src, clean_path=clean[0])
        slug = src.stem.replace(' ', '_')
        target = cache / f'fit_{slug}.pdf'
        doc.save(target, garbage=4, deflate=True)
        doc.close()
        out = fitz.open(target)
        original = fitz.open(src)
        reference = ROOT / CFG['paths']['samples'] / f"{CFG['output_prefix']}_{slug}_{CFG['output_version']}.pdf"
        indices = list(range(len(out)))
        with fitz.open(reference) as sample:
            for i in indices:
                ours = Image.fromarray(raster(out[i], CFG['pages']['diagnostic_dpi']))
                theirs = Image.fromarray(raster(sample[i+1], CFG['pages']['diagnostic_dpi']))
                canvas = Image.new('RGB', (ours.width+theirs.width, max(ours.height,theirs.height)+24), 'white')
                canvas.paste(ours,(0,24)); canvas.paste(theirs,(ours.width,24))
                ImageDraw.Draw(canvas).text((5,3),'generated LEFT / sample RIGHT',fill='black')
                canvas.save(debug / f'fit_{slug}_p{i+1}.png')
        checks = {'a_count':len(original)==len(out), 'b_geometry':True,
                  'c_no_number_text':True, 'd_same_content_text':True,
                  'e_footer_text':True, 'f_comparison_pages':[i+1 for i in indices]}
        for i, (p,q) in enumerate(zip(original,out)):
            checks['b_geometry'] &= (p.rect==q.rect and p.rotation==q.rotation and
                                      p.mediabox==q.mediabox and p.cropbox==q.cropbox)
            checks['c_no_number_text'] &= not number_candidates(q,CFG['pages'])
            expected=p.get_text()
            for item in report['pages'][i]['removed']:
                expected=expected.replace(item['text']+'\n','')
            actual='\n'.join(s for s in q.get_text().splitlines() if s.strip()!='BALATAR.GROUP')
            checks['d_same_content_text'] &= actual == expected.rstrip('\n')
            checks['e_footer_text'] &= 'BALATAR.GROUP' in q.get_text()
        report.update(source=src.name, checks=checks)
        (debug/f'fit_{slug}_qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        records.append((original,out,report))
    yield records
    for original,out,_ in records:
        original.close();out.close()


@pytest.mark.parametrize('index',range(4))
def test_sample_acceptance(processed,index):
    original,out,report = processed[index]
    assert all(value for key,value in report['checks'].items() if key!='f_comparison_pages'), report['checks']
    for p,q in zip(original,out):
        assert image_hashes(original,p)==image_hashes(out,q)
        assert len(q.get_drawings()) >= len(p.get_drawings())
        assert not list(q.annots() or [])
    for page in report['pages']:
        for piece in page['pieces']:
            if piece['part'] != 'middle':
                assert piece['scale_x']==pytest.approx(piece['scale_y'], abs=1e-12)
    # Coverage must be reported honestly, not suppressed to meet acceptance.
    assert report['content_uncovered'] == (not any(
        x['meaningful_ink_pixels'] for p in report['pages'] for x in p['coverage_after_fit']))
    assert report['content_uncovered']


@pytest.mark.parametrize('index',range(4))
def test_no_pixel_change_outside_border_and_removed_numbers(processed,index):
    original,out,report=processed[index]
    # Bake has its own independently checked user-authorized tolerance. From the
    # baked baseline onwards the original ZERO exterior-change requirement stays.
    baseline=fitz.open();baseline.insert_pdf(original)
    _preserve_rendering_attributes(original,baseline)
    baseline.bake(annots=True,widgets=False)
    measurements=[]
    for p,q,entry in zip(baseline,out,report['pages']):
        remove_numbers(p,CFG['pages'])
        fit_content(p,entry['pieces'],CFG['pages'])
        before,after=raster(p,150),raster(q,150)
        change=np.any(before!=after,axis=2)
        boxes=[x['bbox'] for x in entry['pieces']]
        for box in boxes:
            x0,y0,x1,y1=(fitz.Rect(box)*(150/72)).irect
            change[max(y0,0):min(y1,change.shape[0]),max(x0,0):min(x1,change.shape[1])]=False
        assert not change.any(), (report['source'],entry['page'],int(change.sum()))
        measurements.append({'page':entry['page'],'outside_strip_differences':int(change.sum())})
    baseline.close()
    slug=Path(report['source']).stem.replace(' ','_')
    (ROOT/CFG['paths']['debug']/f'fit_{slug}_exterior.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')


def test_widget_bake_is_attempted_and_structural_change_is_rejected():
    source=fitz.open();p=source.new_page(width=600,height=800)
    a=p.add_rect_annot(fitz.Rect(30,30,60,60));a.set_colors(stroke=(1,1,1));a.update()
    widget=fitz.Widget();widget.field_name='example';widget.field_type=fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect=fitz.Rect(100,100,200,130);widget.field_value='value';p.add_widget(widget)
    out=fitz.open(stream=source.tobytes(),filetype='pdf')
    # In this synthetic widget PDF MuPDF adds a drawing during bake. The required
    # invariant must reject it; widgets are neither removed nor used to skip bake.
    with pytest.raises(ValueError,match="'widgets_before': 1, 'widgets_after': 1"):
        bake_annotations(out,CFG['pages'])
    assert not list(out[0].annots() or [])
    assert len(list(out[0].widgets()))==1
    assert len(list(source[0].annots()))==1
    out.close();source.close()


def test_meaningful_ink_colors():
    colors=np.array([[[202,235,253],[255,255,255],[0,0,0],[255,0,0],[0,150,255],[100,210,0],[255,80,80],[255,134,134],[81,81,81],[227,169,177],[248,97,99]]],dtype=np.uint8)
    assert meaningful_ink(colors,CFG['pages']).tolist()==[[False,False,True,True,True,True,False,False,True,False,False]]


def test_clean_border_preserves_vectors_and_pixels(clean):
    assets=discover_assets(CFG,ROOT)
    with fitz.open(assets['border']) as src, fitz.open(clean[0]) as dst:
        assert dst[0].get_text().strip()=='BALATAR.GROUP'
        a,b=src[0].get_drawings(),dst[0].get_drawings()
        assert len(a)==len(b)==clean[1]['vector_paths']
        for x,y in zip(a,b):
            assert x['type']==y['type']
            assert tuple(x['rect'])==pytest.approx(tuple(y['rect']),abs=0.001)
        old,new=raster(src[0],150),raster(dst[0],150)
        mask=np.any(old!=new,axis=2)
        box=fitz.Rect(clean[1]['bbox'])* (150/72)
        x0,y0,x1,y1=box.irect
        assert mask[y0:y1,x0:x1].any()
        mask[y0:y1,x0:x1]=False
        assert not mask.any()


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_rotated_border_visible_coordinates(clean,rotation):
    # A nonsquare crop with nonzero origin catches rotation and box-offset errors.
    source=fitz.open(); p=source.new_page(width=700,height=900)
    p.set_cropbox(fitz.Rect(30,40,670,860));p.set_rotation(rotation)
    with fitz.open(clean[0]) as border:
        geometry=apply_border(p,border,CFG['border'])
        expected=fitz.open();e=expected.new_page(width=p.rect.width,height=p.rect.height)
        apply_border(e,border,CFG['border'])
        a,b=raster(p,72),raster(e,72)
        # Same visual placement; tiny antialias rounding is measured separately.
        assert np.mean(np.any(a!=b,axis=2)) < 0.001
        assert p.rotation==rotation
        for piece in geometry:
            assert p.rect.contains(fitz.Rect(piece['bbox']))
        expected.close()
    source.close()


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_selective_redaction_and_graphics(clean,rotation):
    src=fitz.open();p=src.new_page(width=600,height=800)
    p.set_rotation(rotation)
    # Place source text using visible coordinates, correcting its orientation.
    for xy,text in [((80,100),'42'),((80,p.rect.height-70),'Equation 42'),
                    ((80,p.rect.height-25),'Page 12')]:
        point=fitz.Point(*xy)*p.derotation_matrix
        p.insert_text(point,text,fontsize=10,rotate=rotation)
    p.draw_rect(fitz.Rect(20,20,40,40),color=(1,0,0))
    expected=p.get_text().replace('Page 12\n','')
    before=len(p.get_drawings())
    removed=remove_numbers(p,CFG['pages'])
    assert [x['text'] for x in removed]==['Page 12']
    assert p.get_text()==expected
    assert len(p.get_drawings())==before
    src.close()


def test_image_footer_is_preserved_and_reported(clean):
    src=fitz.open();p=src.new_page(width=600,height=800)
    pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,40,20),False);pix.clear_with(0)
    p.insert_image(fitz.Rect(100,760,140,780),pixmap=pix)
    out,report=process_pages(src,clean_path=clean[0])
    assert not report['pages'][0]['removed']
    assert report['pages'][0]['image_candidates']
    assert image_hashes(src,p)==image_hashes(out,out[0])
    assert report['content_uncovered']
    out.close();src.close()


def test_mixed_pages_keep_all_boxes(clean):
    source=fitz.open()
    for w,h,angle in [(500,700,0),(960,540,0),(700,500,90),(600,800,180),(600,800,270)]:
        p=source.new_page(width=w,height=h);p.set_rotation(angle)
    out,report=process_pages(source,clean_path=clean[0])
    assert len(out)==len(source)
    for p,q in zip(source,out):
        assert (p.rect,p.cropbox,p.mediabox,p.rotation)==(q.rect,q.cropbox,q.mediabox,q.rotation)
        assert 'BALATAR.GROUP' in q.get_text()
    out.close();source.close()
