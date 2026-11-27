"""Restricted formula-to-HTML conversion. No PDF writes or legacy cover hooks."""
from html import escape
import re
import unicodedata
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config, discover_assets


class FormulaSyntaxError(ValueError):
    def __init__(self, code, position):
        self.code, self.position = code, position
        super().__init__(f'{code}: position {position}')


class FormulaGlyphError(ValueError):
    def __init__(self, code, char):
        self.code, self.char = code, char
        super().__init__(f'{code}: {char!r} (U+{ord(char):04X})')


def render_formula_html(text, *, settings=None, font=None):
    """Return (HTML fragment or None, report), without changing ordinary text.

    Optional injected settings/font make conversion independent of filesystem I/O.
    The default entry point reads only project config and the configured Aria font.
    Explicit math symbols also trigger glyph checks; other non-formula text is
    returned to the unchanged legacy path without validating or rewriting it.
    """
    if not isinstance(text, str):
        raise TypeError('Formula input must be text')
    cfg = None
    if settings is None:
        cfg = load_config(DEFAULT_CONFIG)
        settings = cfg['qa']['formula']
    markers = {settings['superscript_marker']: 'sup', settings['subscript_marker']: 'sub'}
    opening, closing = settings['opening_brace'], settings['closing_brace']
    tokens = list(markers) + [opening, closing]
    if any(len(v) != 1 for v in tokens) or len(set(tokens)) != len(tokens):
        raise ValueError('Formula syntax tokens must be distinct single characters')
    atom = re.compile(settings['atom_pattern'])
    start = re.compile('(' + settings['base_pattern'] + ')(?=[' + re.escape(''.join(markers)) + '])')
    fragments, printed, formulas = [], [], []
    cursor = 0
    while match := start.search(text, cursor):
        prefix = text[cursor:match.start()]
        fragments.append(escape(prefix)); printed.append(prefix)
        body = [escape(match.group(1))]; printed.append(match.group(1))
        end = match.end(); used = set()
        while end < len(text) and text[end] in markers:
            marker = text[end]; tag = markers[marker]
            if marker in used:
                raise FormulaSyntaxError('FORMULA_REPEATED_SCRIPT', end)
            used.add(marker); end += 1
            if end >= len(text):
                raise FormulaSyntaxError('FORMULA_MISSING_SCRIPT', end)
            if text[end] == opening:
                begin = end + 1; end = begin
                while end < len(text) and text[end] != closing:
                    if text[end] == opening or text[end] in markers:
                        raise FormulaSyntaxError('FORMULA_NESTED_GROUP', end)
                    end += 1
                if end == len(text):
                    raise FormulaSyntaxError('FORMULA_UNCLOSED_GROUP', begin - 1)
                value = text[begin:end]
                if not value.strip():
                    raise FormulaSyntaxError('FORMULA_EMPTY_GROUP', begin)
                end += 1
            else:
                script = atom.match(text, end)
                if script is None or script.end() == end:
                    raise FormulaSyntaxError('FORMULA_INVALID_SCRIPT', end)
                value = script.group(); end = script.end()
            body.append('<' + tag + '>' + escape(value) + '</' + tag + '>')
            printed.append(value)
        if end < len(text) and text[end] in (opening, closing):
            raise FormulaSyntaxError('FORMULA_UNEXPECTED_BRACE', end)
        fragments.append('<span dir="ltr" style="direction:ltr;unicode-bidi:isolate">' + ''.join(body) + '</span>')
        formulas.append({'start': match.start(), 'end': end, 'source': text[match.start():end]})
        cursor = end
    tail = text[cursor:]; fragments.append(escape(tail)); printed.append(tail)
    report = {'formula': bool(formulas), 'spans': formulas, 'glyphs_checked': 0}
    if not formulas and not any(char in settings['math_symbols'] for char in text):
        return None, report
    if font is None:
        cfg = cfg or load_config(DEFAULT_CONFIG)
        path = discover_assets(cfg, DEFAULT_CONFIG.parent, roles=['font'])['font']
        font = fitz.Font(fontfile=str(path))
    for char in sorted(set(''.join(printed))):
        # Formatting controls and whitespace have no independently painted glyph.
        if char.isspace() or unicodedata.category(char) in ('Cf', 'Cc'):
            continue
        if not font.has_glyph(ord(char), fallback=0):
            raise FormulaGlyphError('FORMULA_GLYPH_MISSING', char)
        report['glyphs_checked'] += 1
    return ''.join(fragments) if formulas else None, report
