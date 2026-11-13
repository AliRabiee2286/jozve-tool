import hashlib
from pathlib import Path
import numpy as np
import pymupdf as fitz
import pytest
from frame import QAFrame
from qa_pages import process_qa_pages, frame_coverage
from pages import raster
from syllabus import load_config, discover_assets

ROOT = Path(__file__).resolve().parents[1]


def image_hashes(doc, page):
    return sorted(hashlib.sha256(doc.extract_image(i[0])['image']).hexdigest() for i in page.get_images(full=True))


def without_frame(doc, report):
    clone = fitz.open(stream=doc.tobytes(), filetype='pdf')
    for p,r in zip(clone,report['pages']):
        streams=p.get_contents()[:r['content_stream_count']]
        clone.xref_set_key(p.xref,'Contents','['+' '.join(f'{x} 0 R' for x in streams)+']')
    return clone


@pytest.mark.parametrize('path', sorted((ROOT/'tests/data/qa').glob('*.pdf')), ids=lambda p:p.name)
def test_real_a4_number_and_content_preserved(path):
    cfg=load_config(); frame=QAFrame()
    with fitz.open(path) as original:
        before=path.read_bytes()
        out,report=process_qa_pages(original)
        try:
            assert len(out)==len(original)
            for a,b,r in zip(original,out,report['pages']):
                assert (a.rect,a.mediabox,a.cropbox,a.rotation)==(b.rect,b.mediabox,b.cropbox,b.rotation)
                assert r['removed'] and all(x['text'].strip()=='۱' for x in r['removed'])
                # Remove only glyphs in the detected footer rectangle, not every
                # occurrence of the same digit in the question/answer body.
                boxes=[fitz.Rect(item['bbox']) for item in r['removed']]
                expected=[c for span in a.get_texttrace() for c in span['chars']
                          if not any(box.contains(fitz.Point(c[2])) for box in boxes)]
                actual=[c for span in b.get_texttrace() for c in span['chars']]
                assert sorted((c[0],c[1]) for c in actual)==sorted((c[0],c[1]) for c in expected)
                assert image_hashes(original,a)==image_hashes(out,b)
                assert len(b.get_image_info())==len(a.get_image_info())
                assert not any(v['meaningful_ink_pixels'] for v in r['coverage_after_fit'])
            with without_frame(out,report) as clean:
                assert all(not any(x['meaningful_ink_pixels'] for x in frame_coverage(p,frame,cfg['pages'])) for p in clean)
                for a,b,r in zip(original,clean,report['pages']):
                    assert not r['fit']['applied']  # Real fixtures already have safe margins.
                    before_pixels,after_pixels=raster(a,150),raster(b,150)
                    allowed=np.zeros(before_pixels.shape[:2],dtype=bool)
                    for item in r['removed']:
                        x0,y0,x1,y1=(fitz.Rect(item['visible_bbox'])*(150/72)).irect
                        allowed[y0:y1,x0:x1]=True
                    assert np.array_equal(before_pixels[~allowed],after_pixels[~allowed])
        finally:out.close()
        assert path.read_bytes()==before


@pytest.mark.parametrize('rotation', [0,90,180,270])
@pytest.mark.parametrize('collision', [False,True])
def test_rotation_crop_uniform_fit_and_image_preservation(rotation,collision):
    frame=QAFrame();cfg=load_config()
    with fitz.open() as source:
        p=source.new_page(width=650,height=850)
        p.set_cropbox(fitz.Rect(17,23,627,819));p.set_rotation(rotation)
        # Draw in visual coordinates, as the frame API does.
        visible=fitz.Rect(p.rect);derotation=p.derotation_matrix;p.set_rotation(0)
        box=fitz.Rect(10,visible.height/2,40,visible.height/2+20) if collision else fitz.Rect(100,100,130,120)
        p.draw_rect(box*derotation,fill=(0,0,0),color=None)
        p.insert_text((200,200),'CONTENT survives 123',fontsize=12)
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,8,8),False);pix.clear_with(40)
        p.insert_image(fitz.Rect(200,250,220,270),pixmap=pix)
        p.set_rotation(rotation)
        before=raster(p,150);out,report=process_qa_pages(source)
        try:
            q=out[0];r=report['pages'][0]
            assert (q.rect,q.cropbox,q.mediabox,q.rotation)==(p.rect,p.cropbox,p.mediabox,p.rotation)
            assert (r['fit']['scale']<1)==collision
            assert r['fit']['applied']==collision
            assert q.get_text()==p.get_text()
            assert image_hashes(source,p)==image_hashes(out,q)
            assert len(q.get_image_info())==len(p.get_image_info())
            if collision:
                a,b,c,d,_,_=r['fit']['display_matrix'];assert a==d and b==c==0
            with without_frame(out,report) as clean:
                assert not any(v['meaningful_ink_pixels'] for v in frame_coverage(clean[0],frame,cfg['pages']))
                if not collision:assert np.array_equal(before,raster(clean[0],150))
            assert np.array_equal(before,raster(source[0],150))
        finally:out.close()


def test_multi_page_different_sizes_and_rotations():
    with fitz.open() as source:
        for w,h,rotation in [(595,842,0),(842,595,0),(720,1000,90)]:
            p=source.new_page(width=w,height=h);p.insert_text((100,100),'TEXT');p.set_rotation(rotation)
        out,report=process_qa_pages(source)
        try:
            assert len(out)==len(source)==len(report['pages'])
            assert all((a.rect,a.rotation,a.cropbox)==(b.rect,b.rotation,b.cropbox) for a,b in zip(source,out))
        finally:out.close()


def test_failed_fit_is_not_hidden_by_frame(monkeypatch):
    monkeypatch.setattr('qa_pages.fit_qa_content',lambda *args:{'scale':1})
    with fitz.open() as source:
        p=source.new_page();p.draw_rect(fitz.Rect(5,100,40,150),fill=(0,0,0))
        with pytest.raises(ValueError,match='QA_INK_UNDER_FRAME'):process_qa_pages(source)


@pytest.mark.parametrize('rotation', [0,90,180,270])
def test_persian_footer_number_in_visual_orientation(rotation):
    cfg=load_config();font=discover_assets(cfg,ROOT,roles=['font'])['font']
    with fitz.open() as source:
        p=source.new_page(width=650,height=850)
        p.set_cropbox(fitz.Rect(17,23,627,819));p.set_rotation(rotation)
        visible=fitz.Rect(p.rect);derotation=p.derotation_matrix;p.set_rotation(0)
        p.insert_text(fitz.Point(visible.width/2,visible.height-12)*derotation,'۱',
                      fontfile=str(font),fontname='qa_test_aria',fontsize=12,rotate=rotation)
        p.insert_text((200,200),'Keep body 1',fontsize=12)
        p.set_rotation(rotation)
        out,report=process_qa_pages(source)
        try:
            assert len(report['pages'][0]['removed'])==1
            assert report['pages'][0]['removed'][0]['text']=='۱'
            assert 'Keep body 1' in out[0].get_text()
            assert '۱' not in out[0].get_text()
        finally:out.close()


def test_source_graphics_state_does_not_move_frame_or_corrupt_stream_boundary():
    with fitz.open() as source:
        p=source.new_page()
        xref=source.get_new_xref();source.update_object(xref,'<<>>')
        source.update_stream(xref,b'1 0 0 1 20 0 cm\n0 0 0 rg\n100 100 20 20 re f\n')
        p.set_contents(xref)
        before=raster(p,150);out,report=process_qa_pages(source)
        try:
            assert not report['pages'][0]['fit']['applied']
            with without_frame(out,report) as clean:
                assert np.array_equal(before,raster(clean[0],150))
            assert out[0].get_drawings()[1]['items'][0][1].x==pytest.approx(QAFrame().segments[0]['a'][0])
        finally:out.close()
