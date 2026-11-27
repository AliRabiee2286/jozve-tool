"""Legacy cover integration: real syllabus, rendered ink and Aria-only glyphs."""
import copy
from collections import Counter
import hashlib
import json

import numpy as np
import pymupdf as fitz
import pytest

import cover
from cover import CoverGlyphError, build_cover
from formula import FormulaSyntaxError
from report_text import write_report
from syllabus import Syllabus


FIELDS = ('teacher', 'course', 'chapter', 'topic')


@pytest.fixture(scope='module')
def syllabus():
    return Syllabus()


def _ink(page, box, dpi=150):
    pix = page.get_pixmap(dpi=dpi, alpha=False, clip=box)
    pixels = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    ys, xs = np.nonzero(np.min(pixels[:, :, :3], axis=2) < 245)
    assert len(xs) > 10, 'Script must have readable painted ink'
    return fitz.Rect((xs.min() + pix.x) * 72 / dpi, (ys.min() + pix.y) * 72 / dpi,
                     (xs.max() + 1 + pix.x) * 72 / dpi, (ys.max() + 1 + pix.y) * 72 / dpi)


@pytest.mark.parametrize('orientation', ['portrait', 'landscape'])
def test_real_formula_cover_preserves_record_and_readable_superscript(syllabus, orientation):
    record = syllabus.find('physics_math_13')
    original = copy.deepcopy(record)
    values = {field: record[field] for field in FIELDS}
    assert 'e^x' in values['topic']
    document, report = build_cover(record['template_index'], orientation, values)
    try:
        # Check the same serialized/reopened page that a viewer will render.
        saved = document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()
    with fitz.open(stream=saved, filetype='pdf') as document:
        assert record == original and values == {field: original[field] for field in FIELDS}
        assert {field: item['value'] for field, item in report['fields'].items()} == values
        topic = report['fields']['topic']
        region = fitz.Rect(topic['bbox'])
        chars = [(char, span['size']) for block in document[0].get_text('rawdict')['blocks']
                 for line in block.get('lines', []) for span in line['spans']
                 for char in span['chars'] if region.contains(fitz.Point(char['origin']))]
        base, base_size = next((char, size) for char, size in chars if char['c'] == 'e')
        script, script_size = next((char, size) for char, size in chars if char['c'] == 'x')
        assert 0.5 <= script_size / base_size < 0.9
        assert script['origin'][1] < base['origin'][1] - base_size * 0.15
        assert script['origin'][0] > base['origin'][0]
        assert -base_size * 0.1 <= script['bbox'][0] - base['bbox'][2] <= base_size * 0.3
        base_ink = _ink(document[0], fitz.Rect(base['bbox']))
        script_ink = _ink(document[0], fitz.Rect(script['bbox']))
        assert script_ink.y0 < base_ink.y0 and script_ink.y1 < base_ink.y1
        assert script_ink.height >= base_ink.height * 0.4
        assert script_ink.width >= base_ink.width * 0.4
        assert region.contains(script_ink)
        assert '^' not in ''.join(char['c'] for char, _ in chars)
        expected = hashlib.sha256(syllabus.assets['font'].read_bytes()).digest()
        with fitz.open(syllabus.assets['template']) as template:
            template_fonts = {hashlib.sha256(template.extract_font(font[0])[3]).digest()
                              for font in template[report['template_page'] - 1].get_fonts(full=True)}
        fonts = {hashlib.sha256(document.extract_font(font[0])[3]).digest()
                 for font in document[0].get_fonts(full=True)}
        assert expected in fonts and fonts - template_fonts == {expected}
        assert not document[0].get_images()


@pytest.mark.parametrize('text', ['e^{☃}', '☃ e^x', '☃', '√'])
def test_cover_reports_missing_aria_glyph_with_codepoint(syllabus, text, monkeypatch):
    record = syllabus.find('physics_math_13')
    values = {field: record[field] for field in FIELDS}
    values['topic'] = text
    monkeypatch.setattr(cover, '_story', lambda *a, **k: pytest.fail('Glyph failure must precede Story'))
    with pytest.raises(CoverGlyphError) as exc:
        build_cover(record['template_index'], 'portrait', values)
    char = '√' if text == '√' else '☃'
    assert exc.value.code == 'COVER_GLYPH_MISSING'
    assert exc.value.char == char
    assert char in str(exc.value) and f'U+{ord(char):04X}' in str(exc.value)


def test_formula_conversion_runs_once_per_field_before_story(syllabus, monkeypatch):
    record = syllabus.find('physics_math_13')
    values = {field: record[field] for field in FIELDS}
    parsed = []
    parser, story = cover.render_formula_html, cover._story

    def parse(value, **kwargs):
        parsed.append(value)
        return parser(value, **kwargs)

    def checked_story(*args, **kwargs):
        assert parsed == list(values.values())
        return story(*args, **kwargs)

    monkeypatch.setattr(cover, 'render_formula_html', parse)
    monkeypatch.setattr(cover, '_story', checked_story)
    document, _ = build_cover(record['template_index'], 'portrait', values)
    document.close()
    assert parsed == list(values.values())


def test_malformed_formula_is_not_silently_rendered(syllabus):
    record = syllabus.find('physics_math_13')
    values = {field: record[field] for field in FIELDS}
    values['topic'] = 'x^{2'
    with pytest.raises(FormulaSyntaxError):
        build_cover(record['template_index'], 'portrait', values)


def test_formula_html_never_replaces_raw_report_value(syllabus, tmp_path):
    record = syllabus.find('physics_math_13')
    values = {field: record[field] for field in FIELDS}
    document, report = build_cover(record['template_index'], 'portrait', values)
    document.close()
    write_report(tmp_path, [{'files': ['physics_math_13.pdf'], 'status': 'موفق', 'cover': report}], [])
    written = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert {field: item['value'] for field, item in written['items'][0]['cover']['fields'].items()} == values
    assert 'e^x' in written['items'][0]['cover']['fields']['topic']['value']


def test_plain_markup_characters_are_still_escaped(syllabus):
    record = syllabus.find('physics_math_13')
    values = {field: record[field] for field in FIELDS}
    values['topic'] = '<sup>x</sup> & متن'
    document, report = build_cover(record['template_index'], 'portrait', values)
    with document:
        assert report['fields']['topic']['value'] == values['topic']
        region = fitz.Rect(report['fields']['topic']['bbox'])
        chars = [(char, span['size']) for block in document[0].get_text('rawdict')['blocks']
                 for line in block.get('lines', []) for span in line['spans']
                 for char in span['chars'] if region.contains(fitz.Point(char['origin']))]
        literal = '<sup>x</sup>&'
        assert Counter(char['c'] for char, _ in chars if char['c'] in literal) == Counter(literal)
        assert next(size for char, size in chars if char['c'] == 'x') == report['fields']['topic']['font_size']
