"""Source-derived, fixed-point purple frames in visual page coordinates."""
from pathlib import Path
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config, discover_assets


class FrameError(ValueError):
    pass


class QAFrame:
    def __init__(self, config_path=DEFAULT_CONFIG, *, source=None):
        config_path = Path(config_path).resolve()
        cfg = load_config(config_path)
        self.tolerance = cfg['qa']['template_pages']['tolerance']
        self.settings = cfg['qa']['frame']
        spec = cfg['qa']['asset_validation']
        source = source or discover_assets(cfg, config_path.parent, roles=['frame_qa'])['frame_qa']
        with fitz.open(source) as doc:
            if len(doc) != spec['frame_pages'] or doc[0].rotation:
                raise FrameError('QA_FRAME_PAGE_GEOMETRY')
            page = doc[0]
            self.size = (page.rect.width, page.rect.height)
            if page.get_text().strip() or page.get_images():
                raise FrameError('QA_FRAME_UNEXPECTED_CONTENT')
            self.segments = []
            for path in page.get_drawings():
                if path['type'] != 's' or len(path['items']) != 1 or path['items'][0][0] != 'l':
                    raise FrameError('QA_FRAME_GEOMETRY')
                _, a, b = path['items'][0]
                if abs(a.x-b.x) <= self.tolerance:
                    edge = 'left' if a.x < page.rect.width/2 else 'right'
                elif abs(a.y-b.y) <= self.tolerance:
                    edge = 'top' if a.y < page.rect.height/2 else 'bottom'
                else:
                    raise FrameError('QA_FRAME_NON_AXIAL')
                caps = path['lineCap']
                if len(set(caps)) != 1 or path['closePath'] or path['width'] <= 0:
                    raise FrameError('QA_FRAME_STROKE_STYLE')
                if not page.rect.contains(a) or not page.rect.contains(b) or a == b:
                    raise FrameError('QA_FRAME_ENDPOINTS')
                self.segments.append(dict(edge=edge, a=list(a), b=list(b),
                    width=path['width'], color=path['color'], cap=caps[0],
                    join=path['lineJoin'], dashes=path['dashes'], opacity=path['stroke_opacity']))
        if (len(self.segments) != spec['frame_segments'] or
                len({s['color'] for s in self.segments}) != spec['frame_colors'] or
                len({s['width'] for s in self.segments}) != spec['frame_widths'] or
                any(len([s for s in self.segments if s['edge'] == edge]) != spec['frame_widths']
                    or len({s['width'] for s in self.segments if s['edge'] == edge}) != spec['frame_widths']
                    for edge in ('left', 'right', 'top', 'bottom'))):
            raise FrameError('QA_FRAME_GEOMETRY')

    def placements(self, rect):
        rect = fitz.Rect(rect)
        def point(values):
            return fitz.Point(*(value if value < old/2 else new-(old-value)
                for value, old, new in zip(values, self.size, (rect.width, rect.height))))
        result = [dict(s, a=list(point(s['a'])), b=list(point(s['b']))) for s in self.segments]
        for s, original in zip(result, self.segments):
            old_a, old_b = original['a'], original['b']
            axis = 1 if s['edge'] in ('left', 'right') else 0
            if ((s['b'][axis]-s['a'][axis])*(old_b[axis]-old_a[axis]) <= 0 or
                    not rect.contains(fitz.Point(s['a'])) or not rect.contains(fitz.Point(s['b']))):
                raise FrameError('QA_FRAME_TARGET_TOO_SMALL')
        return result

    def inner_rect(self, rect, margin=0):
        parts = self.placements(rect)
        bounds = {}
        for edge in ('left', 'right', 'top', 'bottom'):
            axis = 0 if edge in ('left', 'right') else 1
            lower = edge in ('left', 'top')
            values = [s['a'][axis] + (s['width']/2 if lower else -s['width']/2)
                      for s in parts if s['edge'] == edge]
            bounds[edge] = (max(values)+margin) if lower else (min(values)-margin)
        safe = fitz.Rect(bounds['left'], bounds['top'], bounds['right'], bounds['bottom'])
        if safe.is_empty:
            raise FrameError('QA_FRAME_TARGET_TOO_SMALL')
        return safe

    def bands(self, rect):
        rect = fitz.Rect(rect)
        inner = self.inner_rect(rect, self.settings['content_margin'])
        return {'left': fitz.Rect(0, 0, inner.x0, rect.height),
                'right': fitz.Rect(inner.x1, 0, rect.width, rect.height),
                'top': fitz.Rect(0, 0, rect.width, inner.y0),
                'bottom': fitz.Rect(0, inner.y1, rect.width, rect.height)}

    def apply(self, page):
        parts = self.placements(page.rect)
        rotation, derotation = page.rotation, page.derotation_matrix
        page.set_rotation(0)
        try:
            for s in parts:
                shape = page.new_shape()
                shape.draw_line(fitz.Point(s['a'])*derotation, fitz.Point(s['b'])*derotation)
                shape.finish(color=s['color'], width=s['width'], lineCap=s['cap'],
                             lineJoin=s['join'], dashes=s['dashes'], closePath=False,
                             stroke_opacity=s['opacity'])
                shape.commit(overlay=True)
        finally:
            page.set_rotation(rotation)
        return parts
