from pathlib import Path
import warnings

import pymupdf as fitz
import pytest

from main import process_job
from pages import number_candidates, remove_numbers
from syllabus import Syllabus, load_config


CONFIG = load_config()
SETTINGS = CONFIG['pages']


def _fixture(kind):
    doc = fitz.open()
    page = doc.new_page(width=300, height=315)
    page.insert_text((100, 303), '42', fontsize=11)
    if kind == 'blocked':
        # A vertical body glyph covers both digit boxes. It is a separate line.
        page.insert_text((116, 314), 'W', fontname='hebo', fontsize=38, rotate=90)
    else:
        body_y = 290 if kind == 'collision' else 270
        page.insert_text((96, body_y), 'SAFE BODY 42', fontname='hebo', fontsize=12)
    return doc


def _legacy_remove(page):
    for candidate in number_candidates(page, SETTINGS):
        page.add_redact_annot(candidate['bbox'], fill=False, cross_out=False)
    page.apply_redactions(images=0, graphics=0)


def test_colliding_footer_removes_only_its_digits():
    with _fixture('collision') as source, fitz.open(stream=source.tobytes(), filetype='pdf') as legacy:
        _legacy_remove(legacy[0])
        assert legacy[0].get_text() == 'FE BODY 42\n'

        page = source[0]
        assert [item['text'] for item in remove_numbers(page, SETTINGS)] == ['42']
        assert page.get_text() == 'SAFE BODY 42\n'
        assert not number_candidates(page, SETTINGS)


@pytest.mark.parametrize('label', ['42', 'Page 42'])
def test_no_collision_matches_legacy_pdf_bytes(label):
    with fitz.open() as source:
        page = source.new_page(width=300, height=315)
        page.insert_text((96, 270), 'SAFE BODY 42')
        page.insert_text((100, 303), label)
        original = source.tobytes(no_new_id=True)

    with fitz.open(stream=original, filetype='pdf') as legacy, fitz.open(stream=original, filetype='pdf') as guarded:
        _legacy_remove(legacy[0])
        assert [item['text'] for item in remove_numbers(guarded[0], SETTINGS)] == [label]
        assert guarded[0].get_text() == legacy[0].get_text() == 'SAFE BODY 42\n'
        assert guarded.tobytes(no_new_id=True) == legacy.tobytes(no_new_id=True)


def test_unresolvable_collision_blocks_publication(tmp_path):
    source_path = tmp_path / 'physics_thermo_8.pdf'
    with _fixture('blocked') as source:
        assert [item['text'] for item in number_candidates(source[0], SETTINGS)] == ['42']
        source.save(source_path)

    destination = tmp_path / 'published'
    destination.mkdir()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        result = process_job([source_path], None, Syllabus(), CONFIG, destination, set())
    assert result['status_code'] == 'BLOCKED'
    assert 'حذف متن' in result['error']
    assert not (destination / Path(result['output'])).exists()


def test_guard_blocks_if_redaction_changes_protected_text(monkeypatch):
    original_apply = fitz.Page.apply_redactions

    def remove_body_too(page, *args, **kwargs):
        page.add_redact_annot(page.search_for('BODY')[0], fill=False, cross_out=False)
        return original_apply(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, 'apply_redactions', remove_body_too)
    with _fixture('collision') as doc, pytest.raises(ValueError, match='حذف متن'):
        remove_numbers(doc[0], SETTINGS)
