"""QA content processing; reuse legacy cleanup without modifying its behavior."""
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config
from frame import QAFrame
from pages import bake_annotations, remove_numbers, raster, meaningful_ink, _preserve_rendering_attributes


def frame_coverage(page, frame, settings):
    dpi = settings['diagnostic_dpi']
    image = raster(page, dpi)
    result = []
    for edge, box in frame.bands(page.rect).items():
        x0, y0, x1, y1 = (box * (dpi/72)).irect
        mask = meaningful_ink(image[max(0,y0):min(image.shape[0],y1),
                                    max(0,x0):min(image.shape[1],x1)], settings)
        result.append({'edge': edge, 'bbox': list(box), 'meaningful_ink_pixels': int(mask.sum())})
    return result


def fit_qa_content(page, frame, settings):
    """Same direct stream CTM technique as pages.fit_content, with four safe edges."""
    visible = fitz.Rect(page.rect)
    safe = frame.inner_rect(visible, frame.settings['content_margin'])
    guard = frame.settings['raster_guard_pixels'] * 72/settings['diagnostic_dpi']
    safe = fitz.Rect(safe.x0+guard, safe.y0+guard, safe.x1-guard, safe.y1-guard)
    if safe.is_empty:
        raise ValueError('QA_NO_SAFE_CONTENT_AREA')
    scale = min(1.0, safe.width/visible.width, safe.height/visible.height)
    dx = safe.x0+(safe.width-visible.width*scale)/2
    dy = safe.y0+(safe.height-visible.height*scale)/2
    display = fitz.Matrix(scale, 0, 0, scale, dx, dy)
    rotation, rotate_matrix = page.rotation, page.rotation_matrix
    page.set_rotation(0)
    try:
        pdf_to_visible = page.transformation_matrix * rotate_matrix
    finally:
        page.set_rotation(rotation)
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
    return {'scale': scale, 'safe_bbox': list(safe), 'content_bbox': list(visible*display),
            'display_matrix': list(display), 'pdf_matrix': list(transform)}


def process_qa_pages(source, config_path=DEFAULT_CONFIG, *, frame=None, progress=None):
    cfg = load_config(config_path)
    settings = cfg['pages']
    frame = frame or QAFrame(config_path)
    owned = not isinstance(source, fitz.Document)
    original = fitz.open(source) if owned else source
    out = fitz.open()
    report = {'pages': [], 'warnings': [], 'content_uncovered': True}
    try:
        if original.needs_pass or not len(original):
            raise ValueError('QA_INVALID_SOURCE_PDF')
        out.insert_pdf(original)
        _preserve_rendering_attributes(original, out)
        baked = bake_annotations(out, settings)
        for index, page in enumerate(out):
            if progress is not None:
                progress(index+1, len(out))
            before = frame_coverage(page, frame, settings)
            removed = remove_numbers(page, settings)
            after = frame_coverage(page, frame, settings)
            fitted = {'scale': 1.0, 'applied': False}
            if any(r['meaningful_ink_pixels'] for r in after):
                fitted = dict(fit_qa_content(page, frame, settings), applied=True)
            checked = frame_coverage(page, frame, settings)
            if any(r['meaningful_ink_pixels'] for r in checked):
                raise ValueError(f'QA_INK_UNDER_FRAME: page {index+1}: {checked}')
            image_candidates = []
            for item in page.get_image_info():
                box = fitz.Rect(item['bbox']) * page.rotation_matrix
                if (box.y1 >= page.rect.height*(1-settings['bottom_fraction']) and
                        box.get_area() < page.rect.get_area()*settings['image_warning_max_fraction']):
                    image_candidates.append({'bbox': list(box), 'number_status': 'unknown; image preserved'})
            # Shape insertion can wrap an unbalanced source stream. Do it before
            # recording the content boundary so later QC can isolate the frame.
            page.wrap_contents()
            streams = list(page.get_contents())
            parts = frame.apply(page)
            report['pages'].append({'page': index+1, 'size': list(page.rect), 'rotation': page.rotation,
                'mediabox': list(page.mediabox), 'cropbox': list(page.cropbox), 'removed': removed,
                'bake': baked[index], 'coverage_original': before, 'coverage_after_number_removal': after,
                'fit': fitted, 'coverage_after_fit': checked, 'pieces': parts,
                'content_stream_count': len(streams), 'frame_stream_count': len(page.get_contents())-len(streams)})
            if image_candidates:
                report['warnings'].append({'page': index+1, 'kind': 'image_number_unknown', 'images': image_candidates})
            if baked[index]['widgets_before']:
                report['warnings'].append({'page': index+1, 'kind': 'widgets_preserved', 'count': baked[index]['widgets_before']})
        return out, report
    except Exception:
        out.close()
        raise
    finally:
        if owned:
            original.close()
