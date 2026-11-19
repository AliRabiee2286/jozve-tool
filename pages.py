"""Vector-preserving content-page processing and conservative coverage diagnostics.

process_pages returns an in-memory document plus a report. Content is uniformly
fitted between the bars; any remaining meaningful ink under a bar is rejected.
No cover is created or inserted by this module.
"""
from pathlib import Path
from collections import Counter, defaultdict
from typing import NamedTuple
import re
import unicodedata
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config
from border import clean_border, placements, apply_border
import bake_proof
from bake_review import REASON as BAKE_REVIEW_REASON, save_images


def _preserve_rendering_attributes(source, destination, destination_start=0, preserve_catalog=True):
    """insert_pdf omits /Group: graft it (including any referenced color space).

    Use the object graft API bundled with pinned PyMuPDF, not string substitution
    of xrefs. The original transparency group is required for pixel preservation.
    """
    graft = fitz.Graftmap(destination)
    src = fitz._as_pdf_document(source)
    dst = fitz._as_pdf_document(destination)
    pairs = [(p.xref, destination[i+destination_start].xref, ('Group', 'UserUnit')) for i,p in enumerate(source)]
    if preserve_catalog:
        pairs.append((source.pdf_catalog(), destination.pdf_catalog(), ('OutputIntents',)))
    for old, new, keys in pairs:
        a = fitz.mupdf.pdf_load_object(src, old)
        b = fitz.mupdf.pdf_load_object(dst, new)
        for key in keys:
            value = fitz.mupdf.pdf_dict_gets(a, key)
            if value.m_internal:
                fitz.mupdf.pdf_dict_puts(b, key, fitz.mupdf.pdf_graft_mapped_object(graft.this, value))


def number_matches(text, settings):
    value = unicodedata.normalize('NFKC', text).strip()
    return any(re.fullmatch(pattern, value, re.IGNORECASE)
               for pattern in settings['number_patterns'])


def number_candidates(page, settings):
    """Require a whole extracted line inside the bottom band, never a substring."""
    bottom = page.rect.height * (1-settings['bottom_fraction'])
    found = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            text = ''.join(span['text'] for span in line['spans'])
            box = fitz.Rect(line['bbox'])
            visible = box * page.rotation_matrix
            if visible.y0 >= bottom and visible.y1 <= page.rect.y1 and number_matches(text, settings):
                found.append({'text': text, 'bbox': list(box), 'visible_bbox': list(visible)})
    return found


_TEXT_ORIGIN_TOLERANCE = 0.001  # PDF points. MuPDF rewrites text positions with float rounding.


class _PositionedChar(NamedTuple):
    text: str
    font: str
    origin: tuple
    bbox: fitz.Rect


class _TracedGlyph(NamedTuple):
    char: _PositionedChar
    glyph_id: int
    paint_type: int


def _number_line_characters(page, found):
    """Locate the exact occurrences reported by the line detector."""
    indices = defaultdict(list)
    for index, item in reversed(list(enumerate(found))):
        indices[(tuple(item['bbox']), item['text'])].append(index)
    footers = [[] for _ in found]
    body = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', ()):
            text = ''.join(char['c'] for span in line['spans'] for char in span['chars'])
            matched = indices[(tuple(line['bbox']), text)]
            destination = footers[matched.pop()] if matched else body
            destination.extend(_PositionedChar(c['c'], s['font'], c['origin'], fitz.Rect(c['bbox']))
                               for s in line['spans'] for c in s['chars'] if not c.get('synthetic'))
    return footers, body


def _trace_text(page):
    return [_TracedGlyph(_PositionedChar(chr(code), span['font'], origin, fitz.Rect(box)), glyph, span['type'])
            for span in page.get_texttrace() for code, glyph, origin, box in span['chars']]


def _near_origin(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= _TEXT_ORIGIN_TOLERANCE


def _char_key(char):
    # rawdict can emit an ASCII digit for a glyph whose trace uses Persian or
    # Arabic digits. Normalize identity for target selection only.
    text = str(unicodedata.decimal(char.text)) if char.text.isdecimal() else char.text
    return text, char.font


def _trace_without_targets(trace, targets, protected, *, merge_footer_spaces=False):
    origins = defaultdict(list)
    body_origins = defaultdict(list)
    for index, target in enumerate(targets):
        origins[_char_key(target)].append((index, target.origin))
    for char in protected:
        body_origins[_char_key(char)].append(char.origin)

    seen = set()
    expected = []
    for glyph in trace:
        char = glyph.char
        key = _char_key(char)
        hits = [i for i, xy in origins.get(key, ()) if _near_origin(xy, char.origin)]
        has_body_origin = any(_near_origin(xy, char.origin) for xy in body_origins.get(key, ()))
        if not hits and merge_footer_spaces and char.text.isspace() and not has_body_origin:
            # The extractor can merge overprinted spaces within a numbered line.
            hits = [i for i, _ in origins.get(key, ()) if targets[i].bbox.intersects(char.bbox)]
        if not hits:
            expected.append(glyph)
        else:
            if has_body_origin:
                return None
            # Text can be painted twice at the same location (fill and stroke).
            seen.update(hits)
    return expected if len(seen) == len(targets) else None


def _same_trace(expected, observed):
    return len(expected) == len(observed) and all(
        a.char.text == b.char.text and a.char.font == b.char.font and
        a.glyph_id == b.glyph_id and a.paint_type == b.paint_type and
        _near_origin(a.char.origin, b.char.origin) for a, b in zip(expected, observed))


def _apply_number_boxes(page, boxes):
    for box in boxes:
        page.add_redact_annot(box, fill=False, cross_out=False)
    page.apply_redactions(images=0, graphics=0)


def _whitespace_overlap_is_safe(page, boxes, trace, expected):
    """Resolve space-only edge contacts without mutating the working page."""
    if expected is None:
        return False
    with fitz.open() as probe:
        probe.insert_pdf(page.parent, from_page=page.number, to_page=page.number)
        copy = probe[0]
        if not _same_trace(trace, _trace_text(copy)):
            return False
        _apply_number_boxes(copy, boxes)
        return _same_trace(expected, _trace_text(copy))


def _exclude_rect(box, obstacle):
    intersection = box & obstacle
    if intersection.is_empty:
        return [box]
    return [part for part in (
        fitz.Rect(box.x0, box.y0, box.x1, intersection.y0),
        fitz.Rect(box.x0, intersection.y1, box.x1, box.y1),
        fitz.Rect(box.x0, intersection.y0, intersection.x0, intersection.y1),
        fitz.Rect(intersection.x1, intersection.y0, box.x1, intersection.y1),
    ) if not part.is_empty]


def _digit_redaction_box(digit, protected):
    """Place a small hit rectangle inside the digit and outside traced body boxes."""
    if digit.bbox.is_empty:
        return None
    free = [digit.bbox]
    for glyph in protected:
        obstacle = glyph.char.bbox
        if digit.bbox.intersects(obstacle):
            free = [piece for rect in free for piece in _exclude_rect(rect, obstacle)]
            if not free:
                return None
    area = max(free, key=lambda rect: rect.get_area())
    center = (area.tl + area.br) / 2
    # Apply redactions on intersection. Use the central eighth of the available
    # area to keep the hit away from each boundary.
    dx, dy = area.width / 16, area.height / 16
    return (center.x - dx, center.y - dy, center.x + dx, center.y + dy)


def remove_numbers(page, settings):
    found = number_candidates(page, settings)
    if not found:
        return found

    boxes = [fitz.Rect(item['bbox']) for item in found]
    footers, body = _number_line_characters(page, found)
    error = f'حذف متن در صفحهٔ محتوا {page.number + 1}'
    if not all(footers):
        raise ValueError(f'{error}؛ محل کاراکترهای شماره قابل تطبیق نیست')
    overlaps = [char for char in body if any(char.bbox.intersects(box) for box in boxes)]
    if not overlaps:
        # Preserve the original operators and annotation order for this path.
        _apply_number_boxes(page, [item['bbox'] for item in found])
        return found

    if any(kind == fitz.PDF_ANNOT_REDACT for _, kind, _ in page.annot_xrefs()):
        raise ValueError(f'{error}؛ صفحه کادر حذف از قبل دارد')
    trace = _trace_text(page)
    if all(char.text.isspace() for char in overlaps):
        footer_chars = [char for line in footers for char in line]
        expected = _trace_without_targets(trace, footer_chars, body, merge_footer_spaces=True)
        if _whitespace_overlap_is_safe(page, boxes, trace, expected):
            _apply_number_boxes(page, [item['bbox'] for item in found])
            if not _same_trace(expected, _trace_text(page)):
                raise ValueError(f'{error}؛ کاراکترهای بیرون شماره تغییر کردند')
            return found

    digits = [char for line in footers for char in line if char.text.isdecimal()]
    protected = body + [char for line in footers for char in line if not char.text.isdecimal()]
    expected = _trace_without_targets(trace, digits, protected)
    if not digits or expected is None:
        raise ValueError(f'{error}؛ ارقام شماره از متن دیگر قابل تفکیک نیستند')

    tight_boxes = [_digit_redaction_box(digit, expected) for digit in digits]
    if None in tight_boxes:
        raise ValueError(f'{error}؛ کادر امن برای رقم شماره پیدا نشد')
    _apply_number_boxes(page, dict.fromkeys(tight_boxes))
    if not _same_trace(expected, _trace_text(page)):
        raise ValueError(f'{error}؛ حذف دقیق ارقام با حفظ کاراکترهای دیگر تأیید نشد')

    for item, line in zip(found, footers):
        removed_digits = ''.join(char.text for char in line if char.text.isdecimal())
        if removed_digits != item['text']:
            item.update(number_line=item['text'], text=removed_digits)
    return found


def raster(page, dpi, alpha=False):
    pix = page.get_pixmap(dpi=dpi, alpha=alpha, colorspace=fitz.csRGB)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy()


def measure_paper_rule(page, settings):
    counts = Counter()
    for path in page.get_drawings():
        if path['type'] != 's' or not path['color']:
            continue
        for item in path['items']:
            if (item[0] == 'l' and abs(item[1].y-item[2].y) < settings['rule_horizontal_tolerance']
                    and abs(item[1].x-item[2].x) > page.cropbox.width*settings['rule_min_width_fraction']):
                counts[tuple(round(v*255) for v in path['color'])] += 1
    if counts and counts.most_common(1)[0][1] >= settings['rule_min_repetitions']:
        color, count = counts.most_common(1)[0]
        return {'rgb': list(color), 'repetitions': count}
    return None


def meaningful_ink(image, settings):
    rgb=image[:,:,:3].astype(np.float32)
    ink=np.min(rgb,axis=2) < min(settings['paper_rule_rgb'])-settings['ink_margin']
    # The vertical red paper margin is stronger than the blue horizontal rules.
    # Exclude its measured color and white antialias blends, not arbitrary red ink.
    blue_vector=255-np.asarray(settings['paper_rule_rgb'],dtype=np.float32)
    # At crossings, both paper rules affect the same pixel. The measured channel
    # products also exclude these intersections, instead of leaving false dots.
    alpha=np.clip((255-rgb[:,:,0])/blue_vector[0],0,1)
    blue=255-alpha[:,:,None]*blue_vector
    red_vector=(255-np.asarray(settings['paper_margin_rgb'],dtype=np.float32))/255
    beta=np.clip(np.sum((1-rgb/blue)*red_vector,axis=2)/np.dot(red_vector,red_vector),0,1)
    paper=blue*(1-beta[:,:,None]*red_vector)
    return ink & (np.max(np.abs(rgb-paper),axis=2)>settings['paper_color_tolerance'])


def _bake_failure_reasons(record, threshold):
    reasons = []
    if record['annotations_after']:
        reasons.append('annotations_after')
    if record['outside_annotation_pixels']:
        reasons.append('outside_annotation_pixels')
    if record['max_channel_difference'] > threshold:
        reasons.append('max_channel_difference')
    if not record['text_equal']:
        reasons.append('text_equal')
    if record['widgets_before'] or record['widgets_after']:
        reasons.append('widgets_present')
    if any(record[k+'_before'] != record[k+'_after'] for k in ('widgets', 'images', 'drawings')):
        reasons.append('structure_changed')
    return reasons


def _bake_decision(record, threshold, review_enabled, proof=None):
    reasons = _bake_failure_reasons(record, threshold)
    if not reasons:
        return 'OK'
    if (review_enabled and threshold == 5 and proof is True and
            record['max_channel_difference'] > threshold and
            not (record['widgets_before'] or record['widgets_after']) and
            set(reasons) <= {'max_channel_difference', 'outside_annotation_pixels'}):
        return 'REVIEW'
    return 'BLOCKED'


def bake_annotations(document, settings, *, review_dir=None):
    """Bake on the caller's output copy; reject violations, never rasterize content.

    Measures every page and collects all violations before raising.
    Pixel differences up to bake_max_channel_difference are tolerated both
    inside and outside annotation bboxes (Multiply-blend rounding); only
    pixels exceeding the threshold outside bboxes count as blocking
    outside_annotation_pixels. Rounding-level outside pixels are recorded
    separately in outside_rounding_pixels. At the production cutoff, an exact
    structural proof can route raster-only failures to human REVIEW.
    """
    threshold = settings['bake_max_channel_difference']
    review_enabled = (settings.get('bake_structural_review', True) is True and threshold == 5
                      and review_dir is not None)
    before = []
    proof_doc = None
    try:
        for page in document:
            before.append({'image': raster(page, settings['diagnostic_dpi']),
                           'boxes': [list(a.rect * page.rotation_matrix) for a in page.annots() or []],
                           'widgets': len(list(page.widgets() or [])),
                           'images': len(page.get_images()), 'drawings': len(page.get_drawings()),
                           'text': page.get_text()})
        candidates = [i for i, old in enumerate(before) if old['boxes'] and not old['widgets']]
        if review_enabled and candidates:
            try:
                proof_doc = bake_proof.geometry_document(document)
            except Exception as exc:
                for index in candidates:
                    before[index]['proof_error'] = f'{type(exc).__name__}: {exc}'
            if proof_doc is not None:
                for index in candidates:
                    try:
                        before[index]['proof'] = bake_proof.snapshot(document[index], proof_doc)
                    except Exception as exc:
                        before[index]['proof_error'] = f'{type(exc).__name__}: {exc}'
        document.bake(annots=True, widgets=False)
    finally:
        if proof_doc is not None:
            proof_doc.close()
    result = []
    violations = []
    post_proof_doc = None
    if review_enabled and any('proof' in old for old in before):
        overrides = {old['proof']['page_number']: old['proof']['content_refs']
                     for old in before if 'proof' in old}
        try:
            post_proof_doc = bake_proof.geometry_document(document, overrides)
        except Exception:
            post_proof_doc = None
    for page, old in zip(document, before):
        page_number = page.number
        after = raster(page, settings['diagnostic_dpi'])
        if after.shape != old['image'].shape:
            violations.append((page.number+1, ['raster_size_changed'], {'max_channel_difference': 255,
                'raster_before': old['image'].shape, 'raster_after': after.shape}))
            continue
        delta = np.abs(after.astype(np.int16)-old['image'].astype(np.int16))
        per_pixel_max = delta.max(axis=2)
        changed = per_pixel_max > 0
        allowed = np.zeros(changed.shape, dtype=bool)
        margin = settings['bake_bbox_margin_pixels']
        for box in old['boxes']:
            x0,y0,x1,y1 = (fitz.Rect(box)*(settings['diagnostic_dpi']/72)).irect
            allowed[max(0,y0-margin):min(allowed.shape[0],y1+margin),
                    max(0,x0-margin):min(allowed.shape[1],x1+margin)] = True
        outside_mask = changed & ~allowed
        outside_above = outside_mask & (per_pixel_max > threshold)
        outside_rounding = outside_mask & (per_pixel_max <= threshold)
        record = {'annotations_before': len(old['boxes']), 'annotations_after': len(list(page.annots() or [])),
                  'annotation_boxes': old['boxes'], 'widgets_before': old['widgets'],
                  'widgets_after': len(list(page.widgets() or [])),
                  'images_before': old['images'], 'images_after': len(page.get_images()),
                  'drawings_before': old['drawings'], 'drawings_after': len(page.get_drawings()),
                  'text_equal': old['text'] == page.get_text(),
                  'different_pixels': int(changed.sum()), 'max_channel_difference': int(per_pixel_max.max()),
                  'outside_annotation_pixels': int(outside_above.sum()),
                  'outside_rounding_pixels': int(outside_rounding.sum())}
        reasons = _bake_failure_reasons(record, threshold)
        decision = _bake_decision(record, threshold, review_enabled)
        if _bake_decision(record, threshold, review_enabled, proof=True) == 'REVIEW':
            try:
                if 'proof' not in old:
                    raise bake_proof.Unproved(old.get('proof_error', 'no same-run AP evidence'))
                if post_proof_doc is None:
                    raise bake_proof.Unproved('post-bake geometry copy unavailable')
                proof = bake_proof.verify(page, old['proof'], post_proof_doc)
                review = {'reason': BAKE_REVIEW_REASON, 'proof': proof}
                if review_dir is not None:
                    visual_diff = np.full_like(after, 255)
                    visual_diff[changed] = (255, 0, 0)
                    review['images'] = save_images(Path(review_dir), page_number+1, old['image'],
                                                   after, visual_diff)
                record['review'] = review
                decision = 'REVIEW'
            except Exception as exc:
                record['structural_proof_failure'] = f'{type(exc).__name__}: {exc}'
        if decision == 'BLOCKED':
            violations.append((page_number+1, reasons, record))
        result.append(record)
    if post_proof_doc is not None:
        post_proof_doc.close()
    if violations:
        worst = max(violations, key=lambda v: v[2]['max_channel_difference'])
        raise ValueError(f'Bake verification failed on page {worst[0]}: {worst[2]}')
    return result


def coverage(page, pieces, settings):
    """Count meaningful ink using the measured paper-rule calibration."""
    dpi = settings['diagnostic_dpi']
    image = raster(page, dpi)
    records = []
    for name in dict.fromkeys(p['strip'] for p in pieces):
        group = [fitz.Rect(p['bbox']) for p in pieces if p['strip'] == name]
        box = fitz.Rect(group[0])
        for rect in group[1:]:
            box |= rect
        x0,y0,x1,y1 = (box * (dpi/72)).irect
        x0,y0 = max(x0,0),max(y0,0)
        x1,y1 = min(x1,image.shape[1]),min(y1,image.shape[0])
        mask = meaningful_ink(image[y0:y1,x0:x1], settings)
        ys,xs = np.nonzero(mask)
        records.append({'strip': name, 'bbox': list(box), 'meaningful_ink_pixels': len(xs),
                        'ink_bbox': [(xs.min()+x0)*72/dpi, (ys.min()+y0)*72/dpi,
                                     (xs.max()+x0+1)*72/dpi, (ys.max()+y0+1)*72/dpi]
                        if len(xs) else None})
    return records


def fit_content(page, pieces, settings):
    """Uniform vector CTM around existing streams; keep resources, Group and boxes.

    Clip to the original visible page before transforming so off-page content
    cannot become newly visible. No nested transparency group or image is added.
    """
    visible = fitz.Rect(page.rect)
    top = max(p['bbox'][3] for p in pieces if p['strip'] == 'header') + settings['fit_top_margin']
    bottom = min(p['bbox'][1] for p in pieces if p['strip'] == 'footer') - settings['fit_bottom_margin']
    if not 0 <= top < bottom <= visible.height:
        raise ValueError('Border strips and margins leave no safe content area')
    scale = min(1.0, (bottom-top)/visible.height)
    dx = (visible.width-visible.width*scale)/2
    dy = top + (bottom-top-visible.height*scale)/2
    display = fitz.Matrix(scale, 0, 0, scale, dx, dy)
    rotation, rotate_matrix = page.rotation, page.rotation_matrix
    page.set_rotation(0)
    try:
        pdf_to_visible = page.transformation_matrix * rotate_matrix
    finally:
        page.set_rotation(rotation)
    # Compose in float64 to avoid accumulated rounding in coordinate conversion.
    def homogeneous(matrix):
        a,b,c,d,e,f = matrix
        return np.array([[a,b,0],[c,d,0],[e,f,1]], dtype=np.float64)
    base = homogeneous(pdf_to_visible)
    composed = base @ homogeneous(display) @ np.linalg.inv(base)
    transform = (composed[0,0],composed[0,1],composed[1,0],composed[1,1],composed[2,0],composed[2,1])
    old_clip = visible * ~pdf_to_visible
    page.wrap_contents()
    streams = page.get_contents()
    numbers = lambda xs: ' '.join(f'{v:.12f}' for v in xs)
    prefix = ('q\n'+numbers(transform)+' cm\n'+
              numbers((old_clip.x0,old_clip.y0,old_clip.width,old_clip.height))+' re W n\n').encode('ascii')
    doc = page.parent
    first, last = doc.get_new_xref(), doc.get_new_xref()
    doc.update_object(first, '<<>>'); doc.update_stream(first, prefix)
    doc.update_object(last, '<<>>'); doc.update_stream(last, b'\nQ\n')
    doc.xref_set_key(page.xref, 'Contents', '['+' '.join(f'{x} 0 R' for x in [first,*streams,last])+']')
    return {'scale': scale, 'safe_bbox': [0,top,visible.width,bottom],
            'content_bbox': list(visible*display), 'display_matrix': list(display),
            'pdf_matrix': list(transform)}


def process_pages(source, config_path=DEFAULT_CONFIG, clean_path=None, progress=None, *, review_dir=None):
    """Copy pages, bake, remove footer text, fit uniformly, overlay vector border.

    source is a path or an open Document (never mutated). Dimensions, boxes and
    rotation remain as supplied. Image footer contents are unknown, never OCR'd.
    """
    config = load_config(config_path)
    if clean_path is None:
        clean_path, _ = clean_border(config_path)
    owned = not isinstance(source, fitz.Document)
    original = fitz.open(source) if owned else source
    out = fitz.open()
    report = {'pages': [], 'warnings': [], 'content_uncovered': True}
    try:
        out.insert_pdf(original)
        _preserve_rendering_attributes(original, out)
        baked = bake_annotations(out, config['pages'], review_dir=review_dir)
        with fitz.open(clean_path) as clean:
            for i, page in enumerate(out):
                if progress is not None:
                    progress(i + 1, len(out))
                pieces = placements(page.rect, clean[0].rect, config['border'])
                before = coverage(original[i], pieces, config['pages'])
                removed = remove_numbers(page, config['pages'])
                after = coverage(page, pieces, config['pages'])
                image_candidates = []
                bottom = page.rect.height * (1-config['pages']['bottom_fraction'])
                for item in page.get_image_info():
                    visible = fitz.Rect(item['bbox']) * page.rotation_matrix
                    if visible.y1 >= bottom and visible.get_area() < page.rect.get_area()*config['pages']['image_warning_max_fraction']:
                        image_candidates.append({'bbox': list(visible),
                                                 'number_status': 'unknown; image preserved'})
                fitted = fit_content(page, pieces, config['pages'])
                fitted_coverage = coverage(page, pieces, config['pages'])
                if any(item['meaningful_ink_pixels'] for item in fitted_coverage):
                    # No border is added to conceal an unsuccessful content placement.
                    raise ValueError(f'Ink remains under strips on page {i+1}: {fitted_coverage}')
                streams_before = len(page.get_contents())
                applied = apply_border(page, clean, config['border'])
                entry = {'page': i+1, 'size': list(page.rect), 'rotation': page.rotation,
                         'removed': removed, 'image_candidates': image_candidates,
                         'bake': baked[i], 'paper_rule': measure_paper_rule(original[i], config['pages']),
                         'coverage_original': before, 'coverage_after_number_removal': after,
                         'fit': fitted, 'coverage_after_fit': fitted_coverage,
                         'border_stream_count': len(page.get_contents())-streams_before,
                         'content_stream_count': streams_before,
                         'pieces': applied}
                report['pages'].append(entry)
                if image_candidates:
                    report['warnings'].append({'page': i+1, 'kind': 'image_number_unknown',
                                               'images': image_candidates})
                if baked[i]['widgets_before']:
                    report['warnings'].append({'page': i+1, 'kind': 'widgets_preserved',
                                               'count': baked[i]['widgets_before']})
        return out, report
    except Exception:
        out.close()
        raise
    finally:
        if owned:
            original.close()
