"""Tests for the bake verification patch: Multiply-blend tolerance and
outside_rounding_pixels.

- test_multiply_highlight_passes: synthetic PDF with a Multiply-blend
  highlight over dense vector content → bake must succeed with the new
  threshold.
- test_real_content_change_blocked: inject a real vector color change after
  actual bake; pixel guards must reject it while all structure checks pass.
- test_outside_rounding_field_present: the bake record must contain both
  outside_annotation_pixels (blocking) and outside_rounding_pixels
  (informational).
- test_all_pages_measured: bake_annotations must measure every page, not
  stop at the first failure.
"""
import numpy as np
import pymupdf as fitz
import pytest

from pages import bake_annotations, raster
from syllabus import load_config

CFG = load_config()
SETTINGS = CFG['pages']


def _make_multiply_highlight_pdf():
    """Create dense vector content and valid Multiply highlight appearances.

    ``add_highlight_annot`` creates the complete visible appearance stream,
    including its ``/BM /Multiply`` ExtGState. No PDF resources or appearance
    commands are rewritten.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Hundreds of independent vector drawings, like the dense NANO pages.
    for y in range(50, 800, 4):
        page.draw_line((50, y), (545, y), color=(0.2, 0.4, 0.6), width=0.5)
    for x in range(50, 550, 8):
        page.draw_line((x, 50), (x, 800), color=(0.6, 0.3, 0.1), width=0.3)

    for rect, color in (
        (fitz.Rect(100, 200, 400, 250), (1, 1, 0)),
        (fitz.Rect(100, 400, 500, 450), (0, 1, 0.5)),
    ):
        _add_multiply_highlight(page, rect, color)

    # PyMuPDF retains annotations on a page held across bake. Production keeps
    # its last loop page alive; use a genuine unannotated control page last.
    # Do not mask this known limitation by deleting or hiding any appearance.
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 30), 'Unannotated control')
    page.draw_rect(fitz.Rect(20, 50, 180, 180), fill=(0.3, 0.6, 0.3))
    return doc


def _add_multiply_highlight(page, rect, color):
    """Add one API-created highlight and validate its PDF appearance."""
    doc = page.parent
    annot = page.add_highlight_annot(rect)
    annot.set_colors(stroke=color)
    annot.set_opacity(0.4)
    annot.update()
    ap_key = doc.xref_get_key(annot.xref, "AP/N")
    assert ap_key[0] == 'xref'
    ap_xref = int(ap_key[1].split()[0])
    ap_object = doc.xref_object(ap_xref)
    assert '/Type /XObject' in ap_object
    assert '/Subtype /Form' in ap_object
    assert '/BM /Multiply' in ap_object
    assert doc.xref_stream(ap_xref)
    assert doc.xref_is_stream(ap_xref)
    assert b'\nf\n' in doc.xref_stream(ap_xref), 'Highlight must paint a visible fill'
    # Retain the visible API-generated appearance and its complete resources.
    assert b'/H gs' in doc.xref_stream(ap_xref)
    assert doc.xref_get_key(ap_xref, 'Resources/ExtGState/H/BM') == ('name', '/Multiply')
    fitz.TOOLS.mupdf_warnings(reset=True)
    annot.get_pixmap(dpi=SETTINGS['diagnostic_dpi'])
    assert not fitz.TOOLS.mupdf_warnings(reset=True)


def _assert_visible_highlights(doc):
    # Confine Page handles to this helper, releasing them before bake.
    page = doc[0]
    pix = page.get_pixmap(dpi=SETTINGS['diagnostic_dpi'], colorspace=fitz.csRGB,
                          alpha=False, annots=False)
    plain = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    delta = np.abs(raster(page, SETTINGS['diagnostic_dpi']).astype(np.int16)
                   - plain.astype(np.int16))
    assert int(np.any(delta > 5, axis=2).sum()) > 100000
    assert int(delta.max()) > 50
    assert len(page.get_drawings()) > 250


def _assert_structure(record):
    assert record['annotations_after'] == 0
    assert record['text_equal']
    for kind in ('drawings', 'images', 'widgets'):
        assert record[kind + '_before'] == record[kind + '_after']


def test_multiply_highlight_passes():
    """Synthetic PDF with Multiply-blend highlights over vector content
    must pass bake verification with threshold=5."""
    doc = _make_multiply_highlight_pdf()
    settings = dict(SETTINGS)
    assert settings['bake_max_channel_difference'] == 5

    _assert_visible_highlights(doc)
    fitz.TOOLS.mupdf_warnings(reset=True)
    result = bake_annotations(doc, settings)
    assert not fitz.TOOLS.mupdf_warnings(reset=True)
    assert len(result) == 2
    assert result[1]['different_pixels'] == 0
    _assert_structure(result[1])

    page_rec = result[0]
    _assert_structure(page_rec)
    assert page_rec['drawings_before'] > 250
    assert page_rec['max_channel_difference'] > 0
    assert page_rec['outside_rounding_pixels'] > 0
    # Annotations should be removed
    assert page_rec['annotations_before'] >= 2
    assert page_rec['annotations_after'] == 0
    # Max channel difference should be within threshold
    assert page_rec['max_channel_difference'] <= settings['bake_max_channel_difference']
    # No blocking outside pixels
    assert page_rec['outside_annotation_pixels'] == 0
    # outside_rounding_pixels field must exist
    assert 'outside_rounding_pixels' in page_rec
    # Structure preserved
    assert page_rec['text_equal']
    doc.close()


def test_real_content_change_blocked(monkeypatch):
    """A real red-to-blue PDF stream change fails only the pixel guards.

    Bake does not apply redactions. Inject a known content mutation immediately
    after the real bake, without adding/removing drawings, text or resources.
    """
    import ast

    def source():
        doc = fitz.open()
        page = doc.new_page(width=200, height=200)
        page.draw_rect(fitz.Rect(20, 20, 180, 180), color=None, fill=(1, 0, 0))
        page.insert_text((30, 100), 'unchanged text')
        return doc

    with source() as control:
        assert bake_annotations(control, SETTINGS)[0]['max_channel_difference'] == 0

    real_bake = fitz.Document.bake
    with source() as doc:
        xref = doc[0].get_contents()[0]
        stream = doc.xref_stream(xref)
        assert stream.count(b'1 0 0 rg') == 1
        before = raster(doc[0], SETTINGS['diagnostic_dpi'])

        def corrupt_color(document, *args, **kwargs):
            real_bake(document, *args, **kwargs)
            document.update_stream(xref, stream.replace(b'1 0 0 rg', b'0 0 1 rg'))

        monkeypatch.setattr(fitz.Document, 'bake', corrupt_color)
        fitz.TOOLS.mupdf_warnings(reset=True)
        with pytest.raises(ValueError, match='Bake verification failed') as error:
            bake_annotations(doc, SETTINGS)
        assert not fitz.TOOLS.mupdf_warnings(reset=True)
        record = ast.literal_eval(str(error.value).split(': ', 1)[1])
        delta = np.abs(raster(doc[0], SETTINGS['diagnostic_dpi']).astype(np.int16)
                       - before.astype(np.int16)).max(axis=2)
        assert int(delta.max()) == record['max_channel_difference'] == 255
        assert int((delta > 0).sum()) == record['different_pixels'] > 1000
        assert int((delta > SETTINGS['bake_max_channel_difference']).sum()) == record['outside_annotation_pixels']
        assert record['annotations_after'] == 0
        assert record['text_equal']
        for kind in ('drawings', 'images', 'widgets'):
            assert record[kind + '_before'] == record[kind + '_after']


def test_outside_rounding_field_present():
    """Bake record must always contain outside_rounding_pixels, even when
    there are no annotations to bake."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(10, 10, 190, 190), fill=(0.5, 0.5, 0.5))

    settings = dict(SETTINGS)
    result = bake_annotations(doc, settings)
    assert len(result) == 1
    rec = result[0]
    assert 'outside_rounding_pixels' in rec
    assert 'outside_annotation_pixels' in rec
    assert rec['outside_rounding_pixels'] == 0
    assert rec['outside_annotation_pixels'] == 0
    assert rec['max_channel_difference'] == 0
    doc.close()


@pytest.mark.parametrize('threshold', [5, 0])
def test_all_pages_measured(monkeypatch, threshold):
    """Visit every page after bake even when the first annotated page fails."""
    import pages

    with _make_multiply_highlight_pdf() as source, fitz.open() as doc:
        doc.insert_pdf(source, from_page=0, to_page=0)
        doc.insert_pdf(source, from_page=0, to_page=1)
        calls = []

        def measured(page, *args, **kwargs):
            calls.append(page.number)
            return raster(page, *args, **kwargs)

        monkeypatch.setattr(pages, 'raster', measured)
        settings = dict(SETTINGS, bake_max_channel_difference=threshold)
        if threshold == 0:
            with pytest.raises(ValueError, match='Bake verification failed'):
                bake_annotations(doc, settings)
        else:
            result = bake_annotations(doc, settings)
            assert len(result) == 3
            for rec in result:
                _assert_structure(rec)
                assert rec['max_channel_difference'] <= 5
                assert rec['outside_annotation_pixels'] == 0
                assert 'outside_rounding_pixels' in rec
            assert [r['annotations_before'] for r in result] == [2, 2, 0]
            assert result[-1]['different_pixels'] == 0
        assert calls == [0, 1, 2, 0, 1, 2]


def test_threshold_from_config():
    """The same visible fixture passes at five but fails at zero."""
    with _make_multiply_highlight_pdf() as doc:
        assert bake_annotations(doc, SETTINGS)[0]['max_channel_difference'] > 0
    with _make_multiply_highlight_pdf() as doc:
        with pytest.raises(ValueError, match='Bake verification failed'):
            bake_annotations(doc, dict(SETTINGS, bake_max_channel_difference=0))


@pytest.mark.parametrize('level', [5, 6, 16, 17])
def test_outside_threshold_boundary(monkeypatch, level):
    """Controlled raster deltas verify the inclusive boundary; no REVIEW."""
    import ast
    import pages

    with fitz.open() as doc:
        doc.new_page(width=20, height=20)
        calls = 0

        def changed_raster(page, *args, **kwargs):
            nonlocal calls
            image = raster(page, *args, **kwargs)
            calls += 1
            if calls == 2:
                image[0, 0, 0] -= level
            return image

        monkeypatch.setattr(pages, 'raster', changed_raster)
        if level <= SETTINGS['bake_max_channel_difference']:
            rec, = bake_annotations(doc, SETTINGS)
            assert rec['outside_rounding_pixels'] == 1
            assert rec['outside_annotation_pixels'] == 0
        else:
            with pytest.raises(ValueError, match='Bake verification failed') as error:
                bake_annotations(doc, SETTINGS)
            rec = ast.literal_eval(str(error.value).split(': ', 1)[1])
            assert rec['outside_annotation_pixels'] == 1
            assert rec['outside_rounding_pixels'] == 0
        assert rec['max_channel_difference'] == level
        _assert_structure(rec)
