from pathlib import Path
from collections import Counter
import numpy as np
import pymupdf as fitz
import pytest
from qa_cover import QACoverBuilder, CoverError
from frame import QAFrame
from pages import raster
from syllabus import Syllabus
from qa_cover_sweep import records

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def data():
    rows=records(Syllabus(ROOT/'config.yaml'))
    with QACoverBuilder() as builder:
        yield builder,rows


@pytest.mark.parametrize('kind', ['soal','pasokh'])
@pytest.mark.parametrize('case', ['real','long','empty','formula'])
def test_input_size_keeps_content_at_scale_one(data,kind,case):
    builder,rows=data
    candidates=[r for r in rows if r['kind']==kind]
    if case=='long':r=max(candidates,key=lambda r:len(r['topic'] or ''))
    elif case=='formula':r=next(r for r in candidates if '^' in (r['topic'] or ''))
    elif case=='empty':r=next(r for r in candidates if r['course'] and not r['topic'])
    else:r=next(r for r in candidates if r['namak']=='shimi_physic_20_'+kind)
    with fitz.open(next((ROOT/'tests/data/qa').glob('*pasokh.pdf'))) as source:
        size=(source[0].rect.width,source[0].rect.height)
    values={f:r[f] for f in builder.settings['fields']}
    native,native_report=builder.build(kind,r['template_index'],values,'native')
    adapted,report=builder.build(kind,r['template_index'],values,input_size=size)
    try:
        assert report['page_size_policy']=='input'
        assert (adapted[0].rect.width,adapted[0].rect.height)==size
        assert report['content_transform'][:4]==[1,0,0,1]
        dx,dy=report['content_transform'][-2:]
        original=[c for span in native[0].get_texttrace() for c in span['chars']]
        final=[c for span in adapted[0].get_texttrace() for c in span['chars']]
        assert Counter((c[0],c[1]) for c in original)==Counter((c[0],c[1]) for c in final)
        a=sorted(original,key=lambda c:(c[0],c[1],c[2]))
        b=sorted(final,key=lambda c:(c[0],c[1],c[2]))
        for old,new in zip(a,b):assert new[2]==pytest.approx((old[2][0]+dx,old[2][1]+dy),abs=.01)
        for old,new in zip(native[0].get_image_info(hashes=True),adapted[0].get_image_info(hashes=True)):
            assert old['digest']==new['digest']
            assert fitz.Rect(new['bbox']).width==pytest.approx(fitz.Rect(old['bbox']).width,abs=.01)
            assert fitz.Rect(new['bbox']).height==pytest.approx(fitz.Rect(old['bbox']).height,abs=.01)
        assert report['pixel_qc']['outside_values']==0
        assert all(report['fields'][f]['value']==v for f,v in values.items())
        with fitz.open(stream=adapted.tobytes(),filetype='pdf') as reopened:
            assert np.array_equal(raster(adapted[0],150),raster(reopened[0],150))
        # Frame edge bands match a separately drawn frame, with no old Letter frame ghost.
        frame=QAFrame()
        # The source artwork uses a CMYK transparency/proof context. Keep that
        # resource context, but remove ALL painting and draw the reference anew.
        with fitz.open(stream=adapted.tobytes(),filetype='pdf') as ref:
            p=ref[0];ref.xref_set_key(p.xref,'Contents','[]');frame.apply(p)
            with fitz.open(stream=ref.tobytes(),filetype='pdf') as reference:
                expected=raster(reference[0],150)
            actual=raster(adapted[0],150)
            for box in frame.bands(p.rect).values():
                x0,y0,x1,y1=(box*(150/72)).irect
                assert np.array_equal(actual[y0:y1,x0:x1],expected[y0:y1,x0:x1])
    finally:native.close();adapted.close()


@pytest.mark.parametrize('size,code', [(None,'SIZE_REQUIRED'),((842,595),'LANDSCAPE'),
    ((300,500),'CLIP_UNSAFE'),((float('nan'),842),'INVALID_INPUT_SIZE')])
def test_unsafe_input_cover_is_explicit_error(data,size,code):
    builder,_=data
    with pytest.raises(CoverError,match=code):
        builder.build('soal',1,{'course':'درس','chapter':'فصل','topic':'مبحث'},'input',input_size=size)


def test_input_policy_preserves_native_interior_pixels(data):
    builder,_=data
    values={'course':'درس','chapter':'فصل','topic':'مبحث'}
    native,_=builder.build('soal',1,values,'native')
    # Integer raster translation gives an exact comparison, without resampling.
    dpi=builder.settings['qc_dpi'];offset_pixels=50
    offset=offset_pixels*72/dpi
    size=(native[0].rect.width+2*offset,native[0].rect.height+2*offset)
    adapted,report=builder.build('soal',1,values,'input',input_size=size)
    try:
        before,after=raster(native[0],dpi),raster(adapted[0],dpi)
        x0,y0,x1,y1=(fitz.Rect(report['source_clip'])*(dpi/72)).irect
        x0+=1;y0+=1;x1-=1;y1-=1
        assert np.array_equal(before[y0:y1,x0:x1],after[y0+offset_pixels:y1+offset_pixels,x0+offset_pixels:x1+offset_pixels])
    finally:native.close();adapted.close()
