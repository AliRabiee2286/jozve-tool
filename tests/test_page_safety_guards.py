"""Unchanged widgets and the legacy no-collision redaction postcondition."""
import ast
from pathlib import Path
import warnings

import pymupdf as fitz
import pytest

import pages
from main import process_job
from syllabus import Syllabus, load_config


CONFIG = load_config()
SETTINGS = CONFIG['pages']


def _widget_document(*, highlight=False, widget=True):
    document = fitz.open()
    page = document.new_page(width=240, height=320)
    page.insert_text((20, 30), 'Body text remains')
    if widget:
        field = fitz.Widget()
        field.field_name = 'synthetic_field'
        field.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        field.field_value = 'unchanged form'
        field.rect = fitz.Rect(40, 100, 200, 125)
        field.text_fontsize = 10
        page.add_widget(field)
    if highlight:
        annotation = page.add_highlight_annot(fitz.Rect(30, 60, 120, 80))
        annotation.set_opacity(1)
        annotation.update()
        document.xref_set_key(annotation.xref, 'BM', 'null')
    # Avoid the pinned PyMuPDF retained-last-page annotation constraint.
    document.new_page(width=20, height=20)
    return document


def test_unchanged_widget_is_ok(tmp_path):
    with _widget_document() as document:
        records = pages.bake_annotations(document, SETTINGS, review_dir=tmp_path)
        record = records[0]
        assert record['widgets_before'] == record['widgets_after'] == 1
        assert record['annotations_before'] == record['annotations_after'] == 0
        assert record['max_channel_difference'] == 0
        assert record['text_equal']
        assert pages._bake_failure_reasons(record, 5) == []
        assert pages._bake_decision(record, 5, True) == 'OK'
        assert 'review' not in record


@pytest.mark.parametrize('widget', [True, False])
def test_highlight_difference_above_five_never_reviews_widgets(widget, monkeypatch, tmp_path):
    actual_raster = pages.raster
    calls = {}

    def six_level_difference(page, *args, **kwargs):
        image = actual_raster(page, *args, **kwargs)
        calls[page.number] = calls.get(page.number, 0) + 1
        if page.number == 0 and calls[page.number] == 2:
            image[0, 0, 0] -= 6
        return image

    monkeypatch.setattr(pages, 'raster', six_level_difference)
    with _widget_document(highlight=True, widget=widget) as document:
        if widget:
            with pytest.raises(ValueError, match='Bake verification failed') as error:
                pages.bake_annotations(document, SETTINGS, review_dir=tmp_path)
            record = ast.literal_eval(str(error.value).split(': ', 1)[1])
            assert record['widgets_before'] == record['widgets_after'] == 1
            assert record['annotations_before'] == 1
            assert record['annotations_after'] == 0
            assert record['max_channel_difference'] > 5
            assert pages._bake_decision(record, 5, True, proof=True) == 'BLOCKED'
            assert 'review' not in record
        else:
            record = pages.bake_annotations(document, SETTINGS, review_dir=tmp_path)[0]
            assert record['max_channel_difference'] > 5
            assert record['review']['proof']


def test_changed_widget_count_still_blocks(monkeypatch, tmp_path):
    actual_bake = fitz.Document.bake

    def delete_widget(document, *args, **kwargs):
        actual_bake(document, *args, **kwargs)
        page = document[0]
        field = next(page.widgets())
        page.delete_widget(field)

    monkeypatch.setattr(fitz.Document, 'bake', delete_widget)
    with _widget_document() as document:
        with pytest.raises(ValueError, match='Bake verification failed') as error:
            pages.bake_annotations(document, SETTINGS, review_dir=tmp_path)
        record = ast.literal_eval(str(error.value).split(': ', 1)[1])
        assert record['widgets_before'] == 1 and record['widgets_after'] == 0
        assert 'structure_changed' in pages._bake_failure_reasons(record, 5)


def _separated_footer(label='42'):
    document = fitz.open()
    page = document.new_page(width=300, height=315)
    page.insert_text((96, 270), 'SAFE BODY 42')
    page.insert_text((100, 303), label)
    return document


@pytest.mark.parametrize('label', ['42', 'Page 42'])
def test_no_collision_trace_check_keeps_legacy_bytes(label):
    with _separated_footer(label) as source:
        original = source.tobytes(no_new_id=True)
    with fitz.open(stream=original, filetype='pdf') as old, fitz.open(stream=original, filetype='pdf') as new:
        candidates = pages.number_candidates(old[0], SETTINGS)
        pages._apply_number_boxes(old[0], [item['bbox'] for item in candidates])
        assert pages.remove_numbers(new[0], SETTINGS) == candidates
        assert new[0].get_text() == old[0].get_text() == 'SAFE BODY 42\n'
        assert new.tobytes(no_new_id=True) == old.tobytes(no_new_id=True)


def test_no_collision_body_loss_blocks_publication(monkeypatch, tmp_path):
    source_path = tmp_path / 'physics_thermo_8.pdf'
    with _separated_footer() as document:
        page = document[0]
        found = pages.number_candidates(page, SETTINGS)
        footers, body = pages._number_line_characters(page, found)
        assert footers and not any(char.bbox.intersects(fitz.Rect(item['bbox']))
                                   for char in body for item in found)
        document.save(source_path)
    actual_redact = fitz.Page.apply_redactions
    mutations = []

    def remove_body_too(page, *args, **kwargs):
        targets = page.search_for('BODY')
        if targets:
            target, = targets
            page.add_redact_annot(target, fill=False, cross_out=False)
            mutations.append(page.number)
        return actual_redact(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, 'apply_redactions', remove_body_too)
    output = tmp_path / 'published'
    output.mkdir()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        result = process_job([source_path], None, Syllabus(), CONFIG, output, set())
    assert mutations == [0]
    assert result['status_code'] == 'BLOCKED', result
    assert 'حذف متن' in result['error']
    assert not (output / Path(result['output'])).exists()


def _run_no_collision_origin_shift(monkeypatch, tmp_path, *, whitespace, dx=0, dy=0):
    source_path = tmp_path / 'physics_thermo_8.pdf'
    with _separated_footer() as source:
        source.save(source_path)
    original_trace = pages._trace_text
    shifted = []

    def move_origin(page):
        trace = original_trace(page)
        if page.number == 0 and not pages.number_candidates(page, SETTINGS) and not shifted:
            index = next(i for i, glyph in enumerate(trace) if glyph.char.text.isspace() == whitespace)
            glyph = trace[index]
            x, y = glyph.char.origin
            char = glyph.char._replace(origin=(x + dx, y + dy))
            trace[index] = glyph._replace(char=char)
            shifted.append({'text': char.text, 'font': char.font,
                            'glyph_id': glyph.glyph_id, 'paint_type': glyph.paint_type,
                            'origin_before': [x, y], 'origin_after': list(char.origin)})
        return trace

    monkeypatch.setattr(pages, '_trace_text', move_origin)
    output = tmp_path / 'published'
    output.mkdir()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        result = process_job([source_path], None, Syllabus(), CONFIG, output, set())
    assert len(shifted) == 1
    return result, output / result['output'], shifted[0]


def test_no_collision_whitespace_origin_shift_is_allowed_and_recorded(monkeypatch, tmp_path):
    result, output, shift = _run_no_collision_origin_shift(monkeypatch, tmp_path, whitespace=True, dx=0.75)
    assert result['status_code'] in ('OK', 'REVIEW'), result
    assert output.is_file()
    page, = result['pages']
    assert page['trace_whitespace_shifts'] == [shift]
    assert page['removed'][0]['trace_whitespace_shifts'] == [shift]


def test_no_collision_non_whitespace_origin_shift_blocks_publication(monkeypatch, tmp_path):
    result, output, _ = _run_no_collision_origin_shift(monkeypatch, tmp_path, whitespace=False, dx=0.01)
    assert result['status_code'] == 'BLOCKED', result
    assert 'حذف متن' in result['error']
    assert not output.exists()


def test_no_collision_non_whitespace_rounding_is_allowed(monkeypatch, tmp_path):
    result, output, _ = _run_no_collision_origin_shift(monkeypatch, tmp_path, whitespace=False,
                                                       dx=0.00003, dy=-0.00003)
    assert result['status_code'] in ('OK', 'REVIEW'), result
    assert output.is_file()
    page, = result['pages']
    assert page['trace_whitespace_shifts'] == []


def test_no_collision_whitespace_vertical_shift_blocks_publication(monkeypatch, tmp_path):
    result, output, _ = _run_no_collision_origin_shift(monkeypatch, tmp_path, whitespace=True,
                                                       dx=0.75, dy=-0.002)
    assert result['status_code'] == 'BLOCKED', result
    assert 'حذف متن' in result['error']
    assert not output.exists()


@pytest.mark.parametrize('field, value', [('text', '\u00a0'), ('font', 'OtherFont'),
                                          ('glyph_id', 4), ('paint_type', 1)])
def test_whitespace_shift_still_requires_exact_glyph_identity(field, value):
    glyph = pages._TracedGlyph(pages._PositionedChar(' ', 'Helvetica', (0., 0.), fitz.Rect()), 3, 0)
    shifted = glyph._replace(char=glyph.char._replace(origin=(0.75, 0.00003)))
    assert pages._whitespace_trace_shifts([glyph], [shifted])
    if field in ('text', 'font'):
        shifted = shifted._replace(char=shifted.char._replace(**{field: value}))
    else:
        shifted = shifted._replace(**{field: value})
    assert pages._whitespace_trace_shifts([glyph], [shifted]) is None
