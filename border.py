"""Two vector strips with uniform-scale end caps. No content-page rasterization."""
from pathlib import Path
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, discover_assets, load_config


class BorderError(ValueError):
    """The calibrated asset or a requested destination is invalid."""


def clean_border(config_path=DEFAULT_CONFIG, cache_dir=None):
    """Return cache path and evidence; remove just the configured number span."""
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    assets = discover_assets(config, config_path.parent)
    settings = config['border']
    cache_root = (config_path.parent / config['paths']['cache']).resolve()
    directory = Path(cache_dir).resolve() if cache_dir is not None else cache_root
    if directory != cache_root and not directory.is_relative_to(cache_root):
        raise BorderError('Border cache must remain inside the configured cache directory')
    target = directory / settings['clean_filename']
    if target.resolve() in assets.values():
        raise BorderError('Cache destination must not overwrite an asset')
    with fitz.open(assets['border']) as doc:
        if len(doc) != 1 or doc[0].rotation:
            raise BorderError('Calibration requires one unrotated border page')
        page = doc[0]
        if any(abs(a-b) > settings['geometry_tolerance'] for a,b in
               zip((page.rect.width, page.rect.height), settings['source_size'])):
            raise BorderError('Border dimensions differ from calibrated source')
        spans = page.get_texttrace()
        numbers = [s for s in spans if ''.join(chr(c[0]) for c in s['chars']).strip()
                   == settings['number_text']]
        if len(numbers) != 1:
            raise BorderError(f'Expected exactly one border number span; found {len(numbers)}')
        before_drawings = page.get_drawings()
        box = fitz.Rect(numbers[0]['bbox'])
        page.add_redact_annot(box, fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0)
        remaining = page.get_text().strip()
        if remaining != settings['retained_text']:
            raise BorderError(f'Unexpected border text after redaction: {remaining!r}')
        # Redaction may normalize PDF syntax but must preserve the vector geometry.
        if len(page.get_drawings()) != len(before_drawings):
            raise BorderError('Redaction changed the number of vector paths')
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.save(target, garbage=4, deflate=True)
    return target, {'removed_text': settings['number_text'], 'bbox': list(box),
                    'retained_text': remaining, 'vector_paths': len(before_drawings)}


def placements(page_rect, source_rect, settings):
    """Six visible-coordinate rectangles; cap scales are exactly (s, s)."""
    width, height = page_rect.width, page_rect.height
    bw, bh = source_rect.width, source_rect.height
    scale = min(width / bw, height / bh)
    if scale <= 0:
        raise BorderError('Page dimensions must be positive')
    result = []
    for name, strip in settings['strips'].items():
        y0, y1 = strip['y']
        y1 = min(y1, bh)
        left, right = strip['cuts']
        if not 0 <= y0 < y1 <= bh or not 0 < left < right < bw:
            raise BorderError('Invalid strip calibration')
        top = y0 * scale if strip['anchor'] == 'top' else height - (bh-y0)*scale
        bottom = top + (y1-y0)*scale
        sx = (0, left, right, bw)
        dx = (0, left*scale, width-(bw-right)*scale, width)
        for index, part in enumerate(('left', 'middle', 'right')):
            clip = fitz.Rect(sx[index], y0, sx[index+1], y1)
            dest = fitz.Rect(dx[index], top, dx[index+1], bottom)
            result.append({'strip': name, 'part': part, 'clip': list(clip),
                           'bbox': list(dest), 'scale': scale,
                           'scale_x': dest.width/clip.width,
                           'scale_y': dest.height/clip.height})
    return result


def apply_border(page, clean_doc, settings):
    """Overlay strips in displayed orientation without changing page rotation."""
    pieces = placements(page.rect, clean_doc[0].rect, settings)
    rotation, derotation = page.rotation, page.derotation_matrix
    # PyMuPDF's transformation_matrix omits the CropBox offset on rotated pages.
    # Use its unrotated transform for insertion, then restore the original metadata.
    page.set_rotation(0)
    try:
        for item in pieces:
            rect = fitz.Rect(item['bbox']) * derotation
            page.show_pdf_page(rect, clean_doc, 0, clip=fitz.Rect(item['clip']),
                               keep_proportion=False, rotate=rotation, overlay=True)
    finally:
        page.set_rotation(rotation)
    return pieces
