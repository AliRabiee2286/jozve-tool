"""Vector-preserving content-page processing and conservative coverage diagnostics.

process_pages returns an in-memory document plus a report. Content is uniformly
fitted between the bars; any remaining meaningful ink under a bar is rejected.
No cover is created or inserted by this module.
"""
from pathlib import Path
from collections import Counter
import re
import unicodedata
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config
from border import clean_border, placements, apply_border


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


def remove_numbers(page, settings):
    found = number_candidates(page, settings)
    for item in found:
        page.add_redact_annot(item['bbox'], fill=False, cross_out=False)
    if found:
        page.apply_redactions(images=0, graphics=0)
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


def bake_annotations(document, settings):
    """Bake on the caller's output copy; reject violations, never rasterize content."""
    before = []
    for page in document:
        before.append({'image': raster(page, settings['diagnostic_dpi']),
                       'boxes': [list(a.rect * page.rotation_matrix) for a in page.annots() or []],
                       'widgets': len(list(page.widgets() or [])),
                       'images': len(page.get_images()), 'drawings': len(page.get_drawings()),
                       'text': page.get_text()})
    document.bake(annots=True, widgets=False)
    result = []
    for page, old in zip(document, before):
        delta = np.abs(raster(page, settings['diagnostic_dpi']).astype(np.int16)-old['image'].astype(np.int16))
        changed = np.any(delta != 0, axis=2)
        allowed = np.zeros(changed.shape, dtype=bool)
        margin = settings['bake_bbox_margin_pixels']
        for box in old['boxes']:
            x0,y0,x1,y1 = (fitz.Rect(box)*(settings['diagnostic_dpi']/72)).irect
            allowed[max(0,y0-margin):min(allowed.shape[0],y1+margin),
                    max(0,x0-margin):min(allowed.shape[1],x1+margin)] = True
        record = {'annotations_before': len(old['boxes']), 'annotations_after': len(list(page.annots() or [])),
                  'annotation_boxes': old['boxes'], 'widgets_before': old['widgets'],
                  'widgets_after': len(list(page.widgets() or [])),
                  'images_before': old['images'], 'images_after': len(page.get_images()),
                  'drawings_before': old['drawings'], 'drawings_after': len(page.get_drawings()),
                  'text_equal': old['text'] == page.get_text(),
                  'different_pixels': int(changed.sum()), 'max_channel_difference': int(delta.max()),
                  'outside_annotation_pixels': int(changed[~allowed].sum())}
        if (record['annotations_after'] or record['outside_annotation_pixels'] or
                record['max_channel_difference'] > settings['bake_max_channel_difference'] or
                not record['text_equal'] or any(record[k+'_before'] != record[k+'_after']
                                              for k in ('widgets', 'images', 'drawings'))):
            raise ValueError(f'Bake verification failed on page {page.number+1}: {record}')
        result.append(record)
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


def process_pages(source, config_path=DEFAULT_CONFIG, clean_path=None):
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
        baked = bake_annotations(out, config['pages'])
        with fitz.open(clean_path) as clean:
            for i, page in enumerate(out):
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
