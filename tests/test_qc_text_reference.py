from pathlib import Path

import pymupdf as fitz
import pytest

from border import clean_border
from cover import build_cover, effective_orientation
from main import safe_output
from naamak import to_output_name
from pages import _preserve_rendering_attributes, process_pages
from qc import check_pdf, _expected_text_without_removed_footer_lines
from syllabus import Syllabus, load_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config()


def _case(tmp_path, *, body):
    record = Syllabus().find('physics_thermo_8')
    source = fitz.open()
    page = source.new_page(width=600, height=800)
    page.insert_text((90, 450), body, fontsize=12)
    page.insert_text((250, 790), 'Page 42', fontsize=10)
    removed = [{'text': 'Page 42', 'bbox': list(line['bbox']),
                'visible_bbox': list(line['bbox'])}
               for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])
               if ''.join(span['text'] for span in line['spans']) == 'Page 42']
    assert len(removed) == 1

    content, pages_report = process_pages(source)
    cover, cover_report = build_cover(record['template_index'], effective_orientation(source[0]),
        {field: record[field] for field in CONFIG['cover']['fields']})
    result = fitz.open(stream=cover.tobytes(), filetype='pdf')
    result.insert_pdf(content)
    _preserve_rendering_attributes(content, result, 1, preserve_catalog=False)
    output = safe_output(tmp_path / 'qc_text_case', CONFIG)
    path = output / to_output_name(record['namak'])
    result.save(path)
    return source, record, cover, cover_report, pages_report, content, result, path, output, removed


def _check(case, path=None):
    source, record, cover, cover_report, pages_report, _, _, saved, _, _ = case
    return check_pdf(path or saved, source, record, cover_report, pages_report, cover)


def test_exact_position_ignores_only_footer_and_keeps_same_number_in_body(tmp_path):
    case = _case(tmp_path, body='Body contains page number 42 and keeps it.')
    source, _, _, _, pages_report, _, result, _, _, removed = case
    with fitz.open(stream=source.tobytes(), filetype='pdf') as original:
        page = original[0]
        expected = _expected_text_without_removed_footer_lines(page, removed)
        assert expected is not None
        assert expected.count('42') == 1
        assert 'Body contains page number 42 and keeps it.' in expected
    entry = pages_report['pages'][0]
    assert entry['removed'] == removed
    assert _check(case)['checks']['صفحه محتوا 1: متن حفظ شده']
    assert 'Body contains page number 42 and keeps it.' in result[1].get_text()
    assert result[1].get_text().count('42') == 1


def test_removed_positioned_footer_is_excluded_from_reference(tmp_path):
    case = _case(tmp_path, body='Keep the body exactly here.')
    source, _, _, _, pages_report, _, result, _, _, removed = case
    with fitz.open(stream=source.tobytes(), filetype='pdf') as original:
        expected = _expected_text_without_removed_footer_lines(original[0], removed)
        assert expected is not None
        assert 'Page 42' not in expected
        assert pages_report['pages'][0]['removed'][0]['text'] == 'Page 42'
    assert 'Page 42' not in result[1].get_text()
    assert _check(case)['checks']['صفحه محتوا 1: متن حفظ شده']


def test_actual_body_text_loss_is_still_rejected_by_qc(tmp_path):
    case = _case(tmp_path, body='A genuine body marker must stay visible.')
    _, _, _, _, _, _, _, original_path, output, _ = case
    with fitz.open(original_path) as damaged:
        page = damaged[1]
        matches = page.search_for('genuine')
        assert len(matches) == 1
        page.add_redact_annot(matches[0], fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0)
        damaged_path = output / 'damaged.pdf'
        damaged.save(damaged_path)
    quality = _check(case, damaged_path)
    assert quality['checks']['صفحه محتوا 1: متن حفظ شده'] is False
    assert 'صفحه محتوا 1: متن حفظ شده' in quality['advisory_failed']


def test_reference_mapper_fails_closed_if_removed_line_has_no_exact_bbox_match():
    with fitz.open() as document:
        page = document.new_page(width=200, height=200)
        page.insert_text((30, 40), 'Body 42')
        wrong = [{'text': '42', 'bbox': [100, 100, 120, 120]}]
        assert _expected_text_without_removed_footer_lines(page, wrong) is None
