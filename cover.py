"""Vector Persian cover pages. No PDF text extraction is used for output QC.

build_cover(index, orientation, values) -> (one-page Document, QC report).
Caller owns the returned Document and decides where to save it.
"""
from pathlib import Path
from html import escape
import math
import hashlib
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config, discover_assets


class CoverError(ValueError):
    """Missing template, ambiguous geometry, invalid value, or unfit text."""


class TextFitError(CoverError):
    pass


def effective_orientation(page):
    if page.rect.width == page.rect.height:
        raise CoverError('Square page has no portrait/landscape orientation')
    return 'landscape' if page.rect.width > page.rect.height else 'portrait'


def select_template(document, template_index, orientation):
    if orientation not in ('portrait', 'landscape'):
        raise CoverError(f'Unsupported orientation: {orientation!r}')
    pages = [p.number for p in document if effective_orientation(p) == orientation]
    if type(template_index) is not int or not 1 <= template_index <= len(pages):
        raise CoverError(f'Template {template_index!r} absent for {orientation}: {len(pages)} available')
    return pages[template_index - 1]


def detect_regions(page, settings):
    """Read ONLY the blank template: four label baselines and containing vector rectangle."""
    spans = [s for b in page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']
             for line in b.get('lines', []) for s in line['spans']
             if abs(s['size'] - settings['label_size_hint']) <= settings['label_size_tolerance']]
    groups = []
    for span in sorted(spans, key=lambda s: s['origin'][1]):
        if groups and abs(span['origin'][1] - groups[-1][0]['origin'][1]) <= span['size'] * settings['row_group_em']:
            groups[-1].append(span)
        else:
            groups.append([span])
    if len(groups) != len(settings['fields']):
        raise CoverError(f'Expected four label rows; found {len(groups)}')
    origins = [sum(s['origin'][1] for s in g) / len(g) for g in groups]
    sizes = [sum(s['size'] for s in g) / len(g) for g in groups]
    frames = []
    for path in page.get_drawings():
        if path['type'] != 's':
            continue
        for item in path['items']:
            if item[0] == 're':
                r = fitz.Rect(item[1])
                if all(r.contains(fitz.Point(s['origin'])) for g in groups for s in g):
                    if not any(r == old for old in frames):
                        frames.append(r)
    if len(frames) != 1:
        raise CoverError(f'Expected one vector frame around labels; found {len(frames)}')
    frame = frames[0]
    size = min(sizes)
    margin = size * settings['frame_margin_em']
    left = frame.x0 + margin
    # Only horizontal extent of the label is used, never its misleading bbox height.
    right = min(s['bbox'][0] for g in groups for s in g) - size * settings['label_gap_em']
    tops = [max(frame.y0 + margin, y - sz * settings['row_top_em']) for y, sz in zip(origins, sizes)]
    bottoms = tops[1:] + [frame.y1 - margin]
    regions = {field: fitz.Rect(left, top, right, bottom)
               for field, top, bottom in zip(settings['fields'], tops, bottoms)}
    if any(r.is_empty or not frame.contains(r) for r in regions.values()):
        raise CoverError('Invalid or overlapping value geometry')
    return regions, dict(zip(settings['fields'], sizes)), frame


def ink_bbox(page, dpi):
    """Alpha extent of a transparent text-only layer; no decoded PDF characters."""
    pix = page.get_pixmap(dpi=dpi, alpha=True)
    try:
        import numpy as np
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        ys, xs = np.nonzero(a[:, :, -1])
        if not len(xs):
            return None
        bounds = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    except ImportError:
        xs, ys = [], []
        samples = pix.samples
        for y in range(pix.height):
            row = samples[y * pix.stride:(y + 1) * pix.stride]
            occupied = [x for x in range(pix.width) if row[x * pix.n + pix.n - 1]]
            if occupied:
                xs.extend((occupied[0], occupied[-1])); ys.append(y)
        if not xs:
            return None
        bounds = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
    return fitz.Rect(*(v * 72 / dpi for v in bounds))


def _story(value, size, font_path, settings):
    css = ('@font-face {font-family: coveraria; src:url("' + font_path.name + '");}'
           'body {margin:0;padding:0;} p {margin:0;padding:0;font-family:coveraria;'
           f'font-size:{size:.8f}pt;line-height:{settings["line_height"]};'
           'text-align:center;direction:rtl;color:#000000;white-space:pre-wrap;}')
    return fitz.Story(html='<p id="value" dir="rtl">' + escape(value) + '</p>',
                      user_css=css, archive=fitz.Archive(str(font_path.parent)))


def _fit_value(value, region, label_size, max_lines, page_rect, font_path, settings):
    if not isinstance(value, str) or not value.strip():
        raise TextFitError('Cover values must be nonempty strings')
    minimum = settings['min_scale']
    scales = [max(minimum, 1 - i * settings['scale_step'])
              for i in range(math.ceil((1 - minimum) / settings['scale_step']) + 1)]
    font_hash = hashlib.sha256(font_path.read_bytes()).digest()
    for scale in dict.fromkeys(scales):
        size = label_size * scale
        story = _story(value, size, font_path, settings)
        more, filled = story.place(fitz.Rect(0, 0, region.width, page_rect.height))
        height = fitz.Rect(filled).height
        count = int(round(height / (size * settings['line_height'])))
        if more or count < 1 or count > max_lines or height > region.height:
            continue
        # Deliberately taller than the region: clipping cannot conceal a vertical spill.
        y = region.y0 + (region.height - height) / 2
        draw_box = fitz.Rect(region.x0, y, region.x1, y + height + size * settings['guard_em'])
        layer = fitz.open()
        p = layer.new_page(width=page_rect.width, height=page_rect.height)
        spare, applied = p.insert_htmlbox(draw_box, _story(value, size, font_path, settings), scale_low=1)
        if spare < 0 or applied != 1:
            layer.close(); continue
        fonts = p.get_fonts(full=True)
        if not fonts or any(hashlib.sha256(layer.extract_font(f[0])[3]).digest() != font_hash for f in fonts):
            layer.close()
            raise CoverError('Text used a font other than the configured Aria file')
        ink = ink_bbox(p, settings['qc_dpi'])
        if ink is None or not region.contains(ink):
            layer.close(); continue
        return layer, {'value': value, 'bbox': list(region), 'ink_bbox': list(ink),
                       'font_size': size, 'label_size': label_size, 'scale': scale,
                       'line_count': count, 'max_lines': max_lines,
                       'layout_height': height, 'layout_box': list(draw_box), 'font_embedded': True}
    raise TextFitError(f'Text does not fit in {max_lines} lines at >= {minimum:.0%}: {value!r}')


def build_cover(template_index, orientation, values, config_path=DEFAULT_CONFIG):
    """Return an editable vector page and exact input/geometry metadata; never save sources."""
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    settings = config['cover']
    if set(values) != set(settings['fields']):
        raise CoverError('Exactly the four configured fields must be supplied')
    assets = discover_assets(config, config_path.parent)
    result = None
    layers = []
    try:
        with fitz.open(assets['template']) as templates:
            selected = select_template(templates, template_index, orientation)
            # select() drops catalog OutputIntents; preserve the source ICC intent.
            result = fitz.open(stream=templates.tobytes(), filetype='pdf')
            kind, intent = result.xref_get_key(result.pdf_catalog(), 'OutputIntents')
            result.select([selected])
            if kind != 'null':
                result.xref_set_key(result.pdf_catalog(), 'OutputIntents', intent)
        page = result[0]
        page.remove_rotation()
        regions, sizes, frame = detect_regions(page, settings)
        report = {'template_index': template_index, 'template_page': selected + 1,
                  'orientation': orientation, 'page_size': [page.rect.width, page.rect.height],
                  'frame_bbox': list(frame), 'fields': {}}
        # Finish all fits before modifying the base page, so a failure yields no partial cover.
        for field, limit in zip(settings['fields'], settings['max_lines']):
            layer, record = _fit_value(values[field], regions[field], sizes[field], limit,
                                       page.rect, assets['font'], settings)
            layers.append(layer); report['fields'][field] = record
        for field, layer in zip(settings['fields'], layers):
            page.draw_rect(regions[field], color=None, fill=(1, 1, 1), overlay=True)
            page.show_pdf_page(page.rect, layer, 0)
        return result, report
    except Exception:
        if result is not None:
            result.close()
        raise
    finally:
        for layer in layers:
            layer.close()
