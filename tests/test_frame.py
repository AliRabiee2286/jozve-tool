from pathlib import Path
import numpy as np
import pymupdf as fitz
import pytest
from frame import QAFrame, FrameError
from pages import raster
from syllabus import load_config, discover_assets

ROOT = Path(__file__).resolve().parents[1]


def test_native_frame_matches_source_pixels_and_styles():
    cfg = load_config(); frame = QAFrame()
    path = discover_assets(cfg, ROOT, roles=['frame_qa'])['frame_qa']
    with fitz.open(path) as source, fitz.open() as out:
        page = out.new_page(width=source[0].rect.width, height=source[0].rect.height)
        frame.apply(page)
        assert np.array_equal(raster(page, 150), raster(source[0], 150))
        for a, b in zip(source[0].get_drawings(), page.get_drawings()):
            assert a['width'] == b['width']
            assert a['lineCap'] == b['lineCap'] and a['lineJoin'] == b['lineJoin']
            assert a['color'] == pytest.approx(b['color'], abs=1e-6)


@pytest.mark.parametrize('size,rotation,crop', [((595,842),0,False), ((842,595),0,False),
    ((595,842),90,False), ((595,842),180,True), ((595,842),270,True), ((720,1000),0,True)])
def test_fixed_distances_on_rotated_and_cropped_pages(size, rotation, crop):
    frame = QAFrame()
    with fitz.open() as doc:
        p = doc.new_page(width=size[0], height=size[1])
        if crop:p.set_cropbox(fitz.Rect(13,19,size[0]-17,size[1]-23))
        p.set_rotation(rotation)
        before = (p.rect, p.cropbox, p.mediabox, p.rotation)
        frame.apply(p)
        assert (p.rect,p.cropbox,p.mediabox,p.rotation) == before
        drawings = p.get_drawings()
        assert len(drawings) == len(frame.segments)
        for actual, source in zip(drawings, frame.segments):
            _, a, b = actual['items'][0]
            for point, old in zip((a*p.rotation_matrix,b*p.rotation_matrix), (source['a'],source['b'])):
                for value, original, old_size, new_size in zip(point,old,frame.size,(p.rect.width,p.rect.height)):
                    expected = original if original < old_size/2 else new_size-(old_size-original)
                    assert value == pytest.approx(expected, abs=frame.tolerance)
            assert actual['width'] == source['width']
        assert not p.get_images() and not p.get_text()


@pytest.mark.parametrize('change', ['missing', 'color', 'diagonal', 'duplicate_width'])
def test_invalid_source_is_rejected(tmp_path, change):
    frame = QAFrame(); path = tmp_path/'invalid.pdf'
    with fitz.open() as doc:
        p = doc.new_page(width=frame.size[0],height=frame.size[1])
        for i,s in enumerate(frame.segments):
            if change == 'missing' and i == 0:continue
            a,b = fitz.Point(s['a']),fitz.Point(s['b'])
            if change == 'diagonal' and i == 0:b.y+=10
            width=frame.segments[0]['width'] if change=='duplicate_width' and i==len(frame.segments)-1 else s['width']
            p.draw_line(a,b,width=width,color=(1,0,0) if change == 'color' and i == 0 else s['color'])
        doc.save(path)
    with pytest.raises(FrameError):QAFrame(source=path)


def test_small_target_rejected():
    with pytest.raises(FrameError):QAFrame().inner_rect(fitz.Rect(0,0,30,30))
