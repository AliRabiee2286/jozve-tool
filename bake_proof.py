"""Fail-closed proof for the specific vector rewrite performed by MuPDF bake."""
from hashlib import sha256
from math import isfinite
import re

import pymupdf as fitz


GEOMETRY_TOLERANCE = 0.5
SCALE_TOLERANCE = 1e-4
TRANSLATION_TOLERANCE = 0.01
IDENTITY = (1, 0, 0, 1, 0, 0)
_NUMBER = rb'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
_SPACE = rb'[\x00\t\n\f\r ]'
_CALL = re.compile(rb'q' + _SPACE + rb'+(' + rb')\s+('.join([_NUMBER] * 6) +
                   rb')\s+cm\s+/([A-Za-z0-9_]+)\s+Do\s+Q(?=' + _SPACE + rb'|$)')
_PDF_WHITESPACE = b'\x00\t\n\f\r '
_M = fitz.mupdf


class Unproved(ValueError):
    """The page is outside the proof's supported structure, or changed."""


def _require(condition, reason):
    if not condition:
        raise Unproved(reason)


def _near(a, b, tolerance):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def _numbers(obj, count):
    _require(_M.pdf_is_array(obj) and _M.pdf_array_len(obj) == count, 'invalid numeric array')
    elements = [_M.pdf_array_get(obj, i) for i in range(count)]
    _require(all(_M.pdf_is_number(x) for x in elements), 'invalid numeric array')
    values = tuple(_M.pdf_to_real(x) for x in elements)
    _require(all(map(isfinite, values)), 'nonfinite numeric array')
    return values


def _rect(obj):
    box = _numbers(obj, 4)
    _require(box[0] < box[2] and box[1] < box[3], 'empty or reversed AP bounds')
    return box


def _entries(obj):
    if _M.pdf_is_null(obj):
        return {}
    _require(_M.pdf_is_dict(obj), 'expected a PDF dictionary')
    entries = {_M.pdf_to_name(_M.pdf_dict_get_key(obj, i)): _M.pdf_dict_get_val(obj, i)
               for i in range(_M.pdf_dict_len(obj))}
    _require(len(entries) == _M.pdf_dict_len(obj), 'duplicate dictionary keys')
    return entries


class _PdfState:
    """Capture resolved values, independent of reference numbers and dict order."""

    def __init__(self, doc):
        self.doc = doc
        self.pdf = fitz._as_pdf_document(doc)
        self.memo = {}
        self.active = set()

    def object(self, xref):
        return _M.pdf_load_object(self.pdf, xref)

    def digest(self, obj):
        xref = _M.pdf_to_num(obj) if _M.pdf_is_indirect(obj) else 0
        ref = (xref, _M.pdf_to_gen(obj)) if xref else None
        if ref in self.memo:
            return self.memo[ref]
        if ref:
            _require(ref not in self.active, 'cyclic PDF resource graph')
            self.active.add(ref)
        try:
            if _M.pdf_is_dict(obj):
                entries = _entries(obj)
                stream = None
                if xref and self.doc.xref_is_stream(xref):
                    stream = sha256(self.doc.xref_stream(xref)).digest()
                    entries = {k: v for k, v in entries.items() if k not in ('Length', 'Filter', 'DecodeParms')}
                value = ('dict', stream, tuple((k, self.digest(v)) for k, v in sorted(entries.items())))
            elif _M.pdf_is_array(obj):
                value = ('array', tuple(self.digest(_M.pdf_array_get(obj, i))
                                        for i in range(_M.pdf_array_len(obj))))
            elif _M.pdf_is_name(obj):
                value = ('name', _M.pdf_to_name(obj))
            elif _M.pdf_is_string(obj):
                value = ('string', _M.pdf_to_string(obj))
            elif _M.pdf_is_bool(obj):
                value = ('bool', _M.pdf_to_bool(obj))
            elif _M.pdf_is_number(obj):
                value = ('number', _M.pdf_to_real(obj))
            elif _M.pdf_is_null(obj) and not ref:
                value = ('null',)
            else:
                raise Unproved('unresolved PDF resource')
            digest = sha256(repr(value).encode('utf-8')).digest()
            if ref:
                self.memo[ref] = digest
            return digest
        finally:
            if ref:
                self.active.remove(ref)

    def resources(self, page_obj):
        resources = _entries(_M.pdf_dict_gets_inheritable(page_obj, 'Resources'))
        forms = _entries(resources.pop('XObject')) if 'XObject' in resources else {}
        return ({name: self.digest(obj) for name, obj in resources.items()}, forms)


def _appearances(state, page):
    appearances = []
    popups = []
    for xref, kind, _ in page.annot_xrefs():
        obj = state.object(xref)
        flags = _M.pdf_to_int(_M.pdf_dict_gets(obj, 'F'))
        if kind == fitz.PDF_ANNOT_POPUP:
            _require(_M.pdf_is_null(_M.pdf_dict_gets(obj, 'AP')) and
                     not _M.pdf_to_bool(_M.pdf_dict_gets(obj, 'Open')), 'visible or custom popup')
            popups.append(_M.pdf_to_num(_M.pdf_dict_gets(obj, 'Parent')))
            continue
        _require(kind in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_INK), 'unsupported annotation type')
        _require(flags in (0, fitz.PDF_ANNOT_IS_PRINT), 'unsupported annotation flags')
        blend = _M.pdf_dict_gets(obj, 'BM')
        alpha = _M.pdf_dict_gets(obj, 'CA')
        _require(_M.pdf_is_null(blend) and (_M.pdf_is_null(alpha) or
                 (_M.pdf_is_number(alpha) and _M.pdf_to_real(alpha) == 1)),
                 'unsupported annotation-level blend or opacity')
        _require(all(_M.pdf_is_null(_M.pdf_dict_gets(obj, key)) for key in ('OC', 'AS', 'ca')),
                 'unsupported annotation state or optional content')
        form = _M.pdf_dict_getp(obj, 'AP/N')
        form_xref = _M.pdf_to_num(form)
        _require(form_xref and state.doc.xref_is_stream(form_xref) and
                 _M.pdf_to_name(_M.pdf_dict_gets(form, 'Subtype')) == 'Form', 'missing normal Form AP')
        bbox = _rect(_M.pdf_dict_gets(form, 'BBox'))
        matrix = _M.pdf_dict_gets(form, 'Matrix')
        matrix = IDENTITY if _M.pdf_is_null(matrix) else _numbers(matrix, 6)
        # A translated origin is supported. Rotation, reflection, scale and shear
        # in the appearance itself are outside this proof.
        _require(matrix[:4] == IDENTITY[:4], 'unsupported AP Matrix linear part')
        rect = _rect(_M.pdf_dict_gets(obj, 'Rect'))
        sx = (rect[2] - rect[0]) / (bbox[2] - bbox[0])
        sy = (rect[3] - rect[1]) / (bbox[3] - bbox[1])
        expected = (sx, 0, 0, sy, rect[0] - sx * (bbox[0] + matrix[4]),
                    rect[1] - sy * (bbox[1] + matrix[5]))
        appearances.append((xref, state.digest(form), expected))
    _require(appearances and all(p in {a[0] for a in appearances} for p in popups),
             'no provable AP or popup without a proven parent')
    return tuple((digest, expected) for _, digest, expected in appearances)


def _geometry(page):
    words = page.get_text('words')
    drawings = page.get_drawings()
    images = page.get_image_info()
    return {
        'word_text': tuple(word[4] for word in words),
        'drawing_types': tuple(d['type'] for d in drawings),
        'words': tuple(tuple(word[:4]) for word in words),
        'drawings': tuple(tuple(d['rect']) for d in drawings),
        'images': tuple(tuple(i['bbox']) for i in images),
    }


def _page_state(state, page):
    page_obj = state.object(page.xref)
    catalog = state.object(state.doc.pdf_catalog())
    user_unit = _M.pdf_dict_gets(page_obj, 'UserUnit')
    _require(page.rotation == 0 and (_M.pdf_is_null(user_unit) or
             (_M.pdf_is_number(user_unit) and _M.pdf_to_real(user_unit) == 1)),
             'unsupported page rotation or UserUnit')
    return {
        'boxes': tuple(tuple(box) for box in (page.rect, page.cropbox, page.mediabox)),
        'geometry': _geometry(page),
        'group': state.digest(_M.pdf_dict_gets(page_obj, 'Group')),
        'output_intents': state.digest(_M.pdf_dict_gets(catalog, 'OutputIntents')),
        'optional_content': state.digest(_M.pdf_dict_gets(catalog, 'OCProperties')),
    }


def geometry_document(document, content_overrides=None):
    """Isolated PDF view with annotation dictionaries excluded from geometry."""
    clone = fitz.open(stream=document.tobytes(), filetype='pdf')
    try:
        content_overrides = content_overrides or {}
        for number in range(len(clone)):
            xref = clone.page_xref(number)
            clone.xref_set_key(xref, 'Annots', 'null')
            if number in content_overrides:
                refs = content_overrides[number]
                actual = tuple(clone[number].get_contents())
                wanted = tuple((document.xref_stream(ref), document.xref_stream_raw(ref)) for ref in refs)
                cloned_streams = tuple((clone.xref_stream(ref), clone.xref_stream_raw(ref)) for ref in actual)
                positions = ([0] if not wanted else
                             [i for i in range(len(cloned_streams)-len(wanted)+1)
                              if cloned_streams[i:i+len(wanted)] == wanted])
                _require(len(positions) == 1, 'geometry copy could not identify original content streams')
                refs = actual[positions[0]:positions[0]+len(wanted)]
                clone.xref_set_key(xref, 'Contents', '[' + ' '.join(f'{ref} 0 R' for ref in refs) + ']')
        return clone
    except BaseException:
        clone.close()
        raise


def _streams(doc, refs):
    return tuple((doc.xref_stream(xref), doc.xref_stream_raw(xref)) for xref in refs)


def snapshot(page, geometry_doc=None):
    """Collect immutable values before bake, without retaining live PDF objects."""
    page_xref, page_number = page.xref, page.number
    state = _PdfState(page.parent)
    appearances = _appearances(state, page)
    resources, xobjects = state.resources(state.object(page.xref))
    content_refs = tuple(page.get_contents())
    owns_geometry_doc = geometry_doc is None
    geometry_doc = geometry_document(state.doc) if owns_geometry_doc else geometry_doc
    try:
        geometry_page = geometry_doc.load_page(page_number)
        _require(_streams(geometry_doc, geometry_page.get_contents()) == _streams(state.doc, content_refs),
                 'geometry-copy content streams differ')
        geometry = _geometry(geometry_page)
    finally:
        if owns_geometry_doc:
            geometry_doc.close()
    page_state = _page_state(state, page)
    return dict(page_state, page_xref=page_xref, page_number=page_number,
                geometry=geometry, appearances=appearances,
                contents=_streams(state.doc, content_refs), content_refs=content_refs,
                resources=resources, xobjects={k: state.digest(v) for k, v in xobjects.items()})


def _calls(stream, wrapped=False):
    remaining = stream.lstrip(_PDF_WHITESPACE)
    if wrapped:
        _require(remaining[:1] == b'Q' and remaining[1:2] in _PDF_WHITESPACE, 'missing closing wrapper')
        remaining = remaining[1:].lstrip(_PDF_WHITESPACE)
    while remaining:
        call = _CALL.match(remaining)
        _require(call, 'unexpected operators after original contents')
        values = tuple(float(n) for n in call.groups()[:6])
        _require(all(map(isfinite, values)), 'nonfinite AP call matrix')
        yield call[7].decode('ascii'), values
        remaining = remaining[call.end():].lstrip(_PDF_WHITESPACE)


def verify(page, old, geometry_doc=None):
    """Prove same-page content, AP resources, call order and AP placement."""
    page_xref, page_number = page.xref, page.number
    _require((page_xref, page_number) == (old['page_xref'], old['page_number']), 'page identity changed')
    _require(not page.annot_xrefs(), 'annotations remain')
    state = _PdfState(page.parent)
    current = _page_state(state, page)
    for key in ('group', 'output_intents', 'optional_content'):
        _require(current[key] == old[key], f'{key} changed')
    refs = page.get_contents()
    current_streams = _streams(state.doc, refs)
    original = old['contents']
    positions = ([0] if not original else
                 [i for i in range(len(current_streams) - len(original) + 1)
                  if current_streams[i:i+len(original)] == original])
    _require(len(positions) == 1, 'original content streams changed')
    position = positions[0]
    source_refs = refs[position:position+len(original)]
    owns_geometry_doc = geometry_doc is None
    geometry_doc = geometry_document(state.doc, {page_number: source_refs}) if owns_geometry_doc else geometry_doc
    try:
        geometry_page = geometry_doc.load_page(page_number)
        _require(_streams(geometry_doc, geometry_page.get_contents()) == original,
                 'post-bake geometry-copy content streams differ')
        source_geometry = _geometry(geometry_page)
    finally:
        if owns_geometry_doc:
            geometry_doc.close()
    added_before, added_after = refs[:position], refs[position+len(original):]
    _require(len(added_before) <= 1 and len(added_after) == 1, 'unexpected content stream insertion')
    if added_before:
        _require(state.doc.xref_stream(added_before[0]).strip(_PDF_WHITESPACE) == b'q',
                 'unexpected opening wrapper')
    previous, geometry = old['geometry'], source_geometry
    _require(all(len(previous[k]) == len(geometry[k]) for k in ('words', 'drawings', 'images')),
             'word, drawing or image count changed')
    _require(len(previous['words']) == len(geometry['words']) and
             previous['word_text'] == geometry['word_text'], 'word count or text changed')
    for left, right in [(old['boxes'], current['boxes']),
                        (previous['words'], geometry['words'])]:
        _require(len(left) == len(right) and all(_near(a, b, GEOMETRY_TOLERANCE) for a, b in zip(left, right)),
                 'word, drawing, image or page geometry changed')
    for key in ('drawings', 'images'):
        old_boxes, new_boxes = list(previous[key]), list(geometry[key])
        old_types = list(previous['drawing_types']) if key == 'drawings' else None
        new_types = list(geometry['drawing_types']) if key == 'drawings' else None
        for index, box in enumerate(old_boxes):
            match = next((i for i, candidate in enumerate(new_boxes)
                          if (old_types is None or old_types[index] == new_types[i]) and
                          _near(box, candidate, GEOMETRY_TOLERANCE)), None)
            _require(match is not None, f'{key} geometry changed')
            new_boxes.pop(match)
            if new_types is not None:
                new_types.pop(match)
        _require(not new_boxes, f'{key} count or geometry changed')
    calls = list(_calls(state.doc.xref_stream(added_after[0]), wrapped=bool(added_before)))
    names = {name for name, _ in calls}
    _require(len(calls) == len(names) == len(old['appearances']), 'AP call missing, duplicated or added')
    resources, xobjects = state.resources(state.object(page.xref))
    _require(resources == old['resources'] and names.isdisjoint(old['xobjects']) and
             set(xobjects) == set(old['xobjects']) | names and
             all(state.digest(xobjects[k]) == v for k, v in old['xobjects'].items()), 'page resources changed')
    for (name, matrix), (digest, expected) in zip(calls, old['appearances']):
        _require(state.digest(xobjects[name]) == digest, 'AP stream, Group or graphic state changed')
        _require(_near(matrix[:4], expected[:4], SCALE_TOLERANCE) and
                 _near(matrix[4:], expected[4:], TRANSLATION_TOLERANCE), 'AP call matrix does not match Rect/BBox/Matrix')
    return {'ap_calls': len(calls), 'original_streams': len(old['contents']),
            'words': len(previous['words']), 'drawings': len(previous['drawings']),
            'images': len(previous['images'])}
