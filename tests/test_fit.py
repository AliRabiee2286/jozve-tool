"""Independent source assembly: PDF affine interpretation precedes device zoom."""
import json
from pathlib import Path
import numpy as np
import pymupdf as fitz
import pytest
from syllabus import load_config, discover_assets
from border import placements
from pages import fit_content, remove_numbers, _preserve_rendering_attributes
from fit_reference import assemble_reference

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()
SOURCES = sorted((ROOT / CFG['paths']['input']).glob('*.pdf'))


def render_direct(page, matrix, width, height):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.clear_with(255)
    dev = fitz.mupdf.fz_new_draw_device(fitz.mupdf.FzMatrix(1,0,0,1,0,0), pix.this)
    fitz.mupdf.fz_run_page(page.this, dev, fitz.JM_matrix_from_py(matrix), fitz.mupdf.FzCookie())
    fitz.mupdf.fz_close_device(dev)
    return np.frombuffer(pix.samples, np.uint8).reshape(height,width,3).copy()


def compare_fit(before, after, fit, pieces):
    zoom = fitz.Matrix(150/72,150/72)
    box = (after.rect * zoom).irect
    # Assemble from pre-fit source data and independently solved geometry. Putting
    # the affine map in the PDF stage keeps its arithmetic order equal to actual
    # rendering; folding it into device zoom was not pixel-equivalent in MuPDF.
    reference_doc,geometry=assemble_reference(before,pieces,CFG['pages'])
    with reference_doc:
        reference=render_direct(reference_doc[before.number],zoom,box.width,box.height)
    assert fit['scale']==geometry['scale']
    actual = render_direct(after, zoom, box.width,box.height)
    diff = np.abs(actual.astype(np.int16)-reference.astype(np.int16))
    changed = np.any(diff,axis=2)
    edge = np.zeros(changed.shape,bool)
    vertical = np.any(reference[1:]!=reference[:-1],axis=2)
    horizontal = np.any(reference[:,1:]!=reference[:,:-1],axis=2)
    edge[1:] |= vertical; edge[:-1] |= vertical
    edge[:,1:] |= horizontal; edge[:,:-1] |= horizontal
    result = {'max_channel_difference':int(diff.max()),'different_pixels':int(changed.sum()),
              'nonedge_differences':int((changed & ~edge).sum())}
    assert result['max_channel_difference'] <= 2, result
    assert result['nonedge_differences'] == 0, result
    return result


@pytest.mark.parametrize('source',SOURCES,ids=lambda p:p.stem)
def test_scaled_render_preserves_colors_and_transparency(source):
    assets=discover_assets(CFG,ROOT)
    rows=[]
    with fitz.open(source) as original, fitz.open() as base, fitz.open() as fitted, fitz.open(assets['border']) as border:
        base.insert_pdf(original); _preserve_rendering_attributes(original,base)
        base.bake(annots=True,widgets=False)
        for page in base:
            remove_numbers(page,CFG['pages'])
        fitted.insert_pdf(base); _preserve_rendering_attributes(base,fitted)
        scales={}
        for p,q in zip(base,fitted):
            text=p.get_text(); images=[base.xref_stream(x[0]) for x in p.get_images()]
            group=fitted.xref_get_key(q.xref,'Group')
            intents=fitted.xref_get_key(fitted.pdf_catalog(),'OutputIntents')
            pieces=placements(q.rect,border[0].rect,CFG['border'])
            info=fit_content(q,pieces,CFG['pages'])
            assert fitted.xref_get_key(q.xref,'Group')==group
            assert fitted.xref_get_key(fitted.pdf_catalog(),'OutputIntents')==intents
            assert q.get_text()==text
            assert [fitted.xref_stream(x[0]) for x in q.get_images()]==images
            key=(p.rect.width,p.rect.height)
            assert scales.setdefault(key,info['scale'])==info['scale']
            rows.append({'page':p.number+1,**compare_fit(p,q,info,pieces)})
    slug=source.stem.replace(' ','_')
    (ROOT/CFG['paths']['debug']/f'fit_{slug}_render.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_fit_rotated_crop(rotation):
    assets=discover_assets(CFG,ROOT)
    with fitz.open() as src,fitz.open() as dst,fitz.open(assets['border']) as border:
        p=src.new_page(width=700,height=900)
        p.draw_rect(fitz.Rect(70,100,400,500),fill=(0.3,0.6,0.8),fill_opacity=0.5)
        p.insert_text((100,150),'Vector content')
        p.set_cropbox(fitz.Rect(30,40,670,860));p.set_rotation(rotation)
        dst.insert_pdf(src);q=dst[0]
        pieces=placements(q.rect,border[0].rect,CFG['border'])
        info=fit_content(q,pieces,CFG['pages'])
        assert (q.rect,q.rotation,q.cropbox,q.mediabox)==(p.rect,p.rotation,p.cropbox,p.mediabox)
        assert q.get_text()==p.get_text()
        compare_fit(p,q,info,pieces)


@pytest.mark.parametrize('mutation',['scale','translation','content'])
def test_reference_rejects_corrupted_fit(mutation):
    assets=discover_assets(CFG,ROOT)
    with fitz.open() as src,fitz.open() as dst,fitz.open(assets['border']) as border:
        p=src.new_page(width=600,height=800)
        p.draw_rect(fitz.Rect(100,100,400,500),fill=(0.2,0.4,0.7))
        p.insert_text((120,150),'Preserve this content')
        dst.insert_pdf(src);q=dst[0]
        pieces=placements(q.rect,border[0].rect,CFG['border'])
        info=fit_content(q,pieces,CFG['pages'])
        if mutation=='content':
            dst.update_stream(q.get_contents()[1],b'')
        else:
            stream=q.get_contents()[0];tokens=dst.xref_stream(stream).decode('ascii').split()
            if mutation=='scale':
                tokens[1]=str(float(tokens[1])*0.99);tokens[4]=str(float(tokens[4])*0.99)
            else:tokens[5]=str(float(tokens[5])+1)
            dst.update_stream(stream,' '.join(tokens).encode('ascii'))
        with pytest.raises(AssertionError):compare_fit(p,q,info,pieces)
