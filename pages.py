"""Vector-preserving content-page processing and conservative coverage diagnostics.

process_pages returns an in-memory document plus a report. Callers must inspect
coverage warnings: a successful transformation does not mean content is uncovered.
No cover is created or inserted by this module.
"""
from pathlib import Path
import re
import unicodedata
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config
from border import clean_border, placements, apply_border


def _preserve_rendering_attributes(source, destination):
    """insert_pdf omits /Group: graft it (including any referenced color space).

    Use the object graft API bundled with pinned PyMuPDF, not string substitution
    of xrefs. The original transparency group is required for pixel preservation.
    """
    graft = fitz.Graftmap(destination)
    src = fitz._as_pdf_document(source)
    dst = fitz._as_pdf_document(destination)
    pairs = [(p.xref, q.xref, ('Group', 'UserUnit')) for p,q in zip(source,destination)]
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


def coverage(page, pieces, settings):
    """Any nonwhite pixel under a strip produces a warning, even paper rules."""
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
        mask = np.any(image[y0:y1,x0:x1] < settings['white_value'], axis=2)
        ys,xs = np.nonzero(mask)
        records.append({'strip': name, 'bbox': list(box), 'nonwhite_pixels': len(xs),
                        'ink_bbox': [(xs.min()+x0)*72/dpi, (ys.min()+y0)*72/dpi,
                                     (xs.max()+x0+1)*72/dpi, (ys.max()+y0+1)*72/dpi]
                        if len(xs) else None})
    return records


def process_pages(source, config_path=DEFAULT_CONFIG, clean_path=None):
    """Copy pages with insert_pdf; remove footer text; overlay vector border.

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
                    if visible.y1 >= bottom:
                        image_candidates.append({'bbox': list(visible),
                                                 'number_status': 'unknown; image preserved'})
                annotations = [{'type': a.type[1], 'bbox': list(a.rect * page.rotation_matrix)}
                               for a in page.annots() or []]
                entry = {'page': i+1, 'size': list(page.rect), 'rotation': page.rotation,
                         'removed': removed, 'image_candidates': image_candidates,
                         'preserved_annotations': annotations,
                         'coverage_original': before, 'coverage_after_number_removal': after,
                         'pieces': apply_border(page, clean, config['border'])}
                report['pages'].append(entry)
                for item in before:
                    if item['nonwhite_pixels']:
                        report['warnings'].append({'page': i+1, 'kind': 'possible_content_coverage', **item})
                if any(item['nonwhite_pixels'] for item in after):
                    report['content_uncovered'] = False
                if image_candidates:
                    report['warnings'].append({'page': i+1, 'kind': 'image_number_unknown',
                                               'images': image_candidates})
                for annotation in annotations:
                    if any(fitz.Rect(annotation['bbox']).intersects(fitz.Rect(p['bbox'])) for p in pieces):
                        report['warnings'].append({'page': i+1, 'kind': 'annotation_over_border',
                                                   **annotation})
        return out, report
    except Exception:
        out.close()
        raise
    finally:
        if owned:
            original.close()
