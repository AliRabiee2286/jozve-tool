import warnings

import pymupdf as fitz
import pytest

from cover import build_cover, effective_orientation
from naamak import to_output_name
from pages import _preserve_rendering_attributes, process_pages
from qc import _expected_text_without_removed_footer_lines, check_pdf
from syllabus import Syllabus, load_config


CFG = load_config()
FOOTER_TEXT = 'Page 42'
BODY_TEXT = '42'


@pytest.fixture
def assembled_with_repeated_page_number(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        record = Syllabus().find('physics_thermo_8')
    source = fitz.open()
    page = source.new_page(width=600, height=800)
    page.insert_text((80, 350), 'Body number 42 remains; marker survives.', fontsize=12)
    page.insert_text((80, 500), BODY_TEXT, fontsize=12)
    page.insert_text((300, 790), FOOTER_TEXT, fontsize=10)
    removed = [{'text': FOOTER_TEXT, 'bbox': list(line['bbox']),
                'visible_bbox': list(line['bbox'])}
               for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])
               if ''.join(span['text'] for span in line['spans']) == FOOTER_TEXT]
    assert len(removed) == 1

    content, page_report = process_pages(source)
    assert page_report['pages'][0]['removed'] == removed
    cover, cover_report = build_cover(record['template_index'], effective_orientation(source[0]),
        {field: record[field] for field in CFG['cover']['fields']})
    result = fitz.open(stream=cover.tobytes(), filetype='pdf')
    result.insert_pdf(content)
    _preserve_rendering_attributes(content, result, 1, preserve_catalog=False)
    filename = to_output_name(record['namak'])
    clean_path = tmp_path / filename
    result.save(clean_path)
    yield source, record, cover, cover_report, page_report, clean_path, filename
    result.close()
    content.close()
    cover.close()
    source.close()


def _check(case, path=None):
    source, record, cover, cover_report, page_report, clean_path, filename = case
    return check_pdf(path or clean_path, source, record, cover_report, page_report, cover,
                     output_name=filename)


def test_positioned_reference_drops_footer_but_keeps_identical_body_number(assembled_with_repeated_page_number):
    source, _, _, _, page_report, path, _ = assembled_with_repeated_page_number
    footer = page_report['pages'][0]['removed']
    expected = _expected_text_without_removed_footer_lines(source[0], footer)
    assert expected is not None
    assert 'Body number 42 remains; marker survives.' in expected
    assert expected.splitlines()[-1] == '42'
    assert 'Page 42' not in expected

    quality = _check(assembled_with_repeated_page_number)
    assert quality['passed'], quality
    assert quality['checks']['صفحه محتوا 1: متن حفظ شده'] is True
    with fitz.open(path) as saved:
        actual = '\n'.join(line for line in saved[1].get_text().splitlines()
                           if line.strip() != CFG['border']['retained_text'])
        assert 'Body number 42 remains; marker survives.' in actual
        assert '42' in actual


def test_deleting_one_real_body_character_still_fails_qc(assembled_with_repeated_page_number, tmp_path):
    _, _, _, _, _, path, filename = assembled_with_repeated_page_number
    with fitz.open(path) as damaged:
        page = damaged[1]
        target, = page.search_for('marker')
        page.add_redact_annot(target, fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0)
        tampered = tmp_path / ('tampered_' + filename)
        damaged.save(tampered)
    quality = _check(assembled_with_repeated_page_number, tampered)
    assert quality['checks']['صفحه محتوا 1: متن حفظ شده'] is False
    assert 'صفحه محتوا 1: متن حفظ شده' in quality['advisory_failed']


def test_reference_fails_closed_when_reported_footer_has_no_line_at_its_bbox():
    with fitz.open() as source:
        page = source.new_page(width=300, height=300)
        page.insert_text((30, 40), 'Body number 42 stays')
        assert _expected_text_without_removed_footer_lines(
            page, [{'text': '42', 'bbox': [100, 100, 120, 120]}]) is None
