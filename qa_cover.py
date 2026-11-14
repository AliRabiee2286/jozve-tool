"""QA covers with source-derived typography and native/input page policies."""
from html import escape
from pathlib import Path
import hashlib
import math
import unicodedata
import copy
import numpy as np
import pymupdf as fitz
from cover import CoverError, TextFitError, ink_bbox
from formula import render_formula_html, FormulaGlyphError
from syllabus import DEFAULT_CONFIG, load_config, discover_assets, normalize_key, is_empty_value


def _pixels(page,dpi):
    pix=page.get_pixmap(dpi=dpi,alpha=False)
    return np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n).copy()


def word_gap_em(page, size, row_tolerance):
    """Measure horizontal whitespace between painted glyph boxes, grouped by baseline.

    Ignore extracted spaces (MuPDF can synthesize a wide space for justification)
    and script baselines; the full-size base glyph anchors each formula word.
    """
    groups = []
    for block in page.get_text('rawdict')['blocks']:
        for line in block.get('lines', []):
            for span in line['spans']:
                if abs(span['size'] - size) > size * row_tolerance:
                    continue
                for char in span['chars']:
                    if char['c'].isspace() or unicodedata.category(char['c']) in ('Cc', 'Cf'):
                        continue
                    y = char['origin'][1]
                    group = next((g for g in groups if abs(g[0] - y) <= size * row_tolerance), None)
                    if group is None:
                        group = [y, []]; groups.append(group)
                    group[1].append(fitz.Rect(char['bbox']))
    maximum = 0.0
    for _, boxes in groups:
        right = None
        for box in sorted(boxes, key=lambda b: b.x0):
            if right is not None:
                maximum = max(maximum, box.x0 - right)
            right = max(right if right is not None else box.x1, box.x1)
    return maximum / size


def detect_qa_regions(page,cfg):
    settings=cfg['qa']['cover'];tol=cfg['qa']['template_pages']['tolerance']
    spans=[s for b in page.get_text('dict',flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']
           for line in b.get('lines',[]) for s in line['spans']]
    chars=[(c,s) for b in page.get_text('rawdict',flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']
           for line in b.get('lines',[]) for s in line['spans'] for c in s['chars']]
    placeholders=[(c,s) for c,s in chars if c['c']==settings['placeholder']]
    if len(placeholders)!=len(settings['fields']):raise CoverError('QA_PLACEHOLDER_COUNT')
    edges={'left':[],'right':[],'top':[],'bottom':[]}
    for drawing in page.get_drawings():
        if drawing['type']!='s':continue
        for item in drawing['items']:
            if item[0]!='l':raise CoverError('QA_FRAME_GEOMETRY')
            _,a,b=item;width=drawing['width']
            if abs(a.x-b.x)<=tol:
                edge='left' if a.x<page.rect.width/2 else 'right'
                edges[edge].append(a.x + (width/2 if edge=='left' else -width/2))
            elif abs(a.y-b.y)<=tol:
                edge='top' if a.y<page.rect.height/2 else 'bottom'
                edges[edge].append(a.y + (width/2 if edge=='top' else -width/2))
            else:raise CoverError('QA_FRAME_GEOMETRY')
    if any(len(v)!=cfg['qa']['asset_validation']['frame_widths'] for v in edges.values()):
        raise CoverError('QA_FRAME_GEOMETRY')
    inner=fitz.Rect(max(edges['left']),max(edges['top']),min(edges['right']),min(edges['bottom']))
    rows=[]
    for field in settings['fields']:
        aliases={normalize_key(a) for a in cfg['headers'][field]}
        labels=[s for s in spans if normalize_key(s['text']) in aliases]
        if len(labels)!=1:raise CoverError('QA_LABEL_AMBIGUOUS: '+field)
        label=labels[0]
        choices=[(c,s) for c,s in placeholders if abs(c['origin'][1]-label['origin'][1])<=label['size']*settings['row_group_em']]
        if len(choices)!=1:raise CoverError('QA_PLACEHOLDER_AMBIGUOUS: '+field)
        char,span=choices[0];erase=fitz.Rect(char['bbox'])
        colons=[c for c,s in chars if c['c']==':' and abs(c['origin'][1]-label['origin'][1])<=label['size']*settings['row_group_em']]
        if len(colons)!=1 or erase.x1>=colons[0]['bbox'][0]:raise CoverError('QA_COLON_OVERLAP: '+field)
        rows.append({'field':field,'placeholder':list(erase),'label_bbox':label['bbox'],
                     'origin':label['origin'],'size':label['size'],'color':fitz.sRGB_to_pdf(label['color'])})
    if any(a['origin'][1]>=b['origin'][1] for a,b in zip(rows,rows[1:])):raise CoverError('QA_ROW_ORDER')
    for index,row in enumerate(rows):
        margin=row['size']*settings['frame_margin_em']
        bottom=rows[index+1]['placeholder'][1] if index+1<len(rows) else inner.y1-margin
        region=fitz.Rect(inner.x0+margin,row['placeholder'][1],row['placeholder'][2],bottom)
        if region.is_empty or not inner.contains(region) or not region.contains(fitz.Rect(row['placeholder'])):
            raise CoverError('QA_VALUE_GEOMETRY: '+row['field'])
        row['region']=list(region)
    return rows,inner


class QACoverBuilder:
    """Reuse read-only template metadata during sweep."""
    def __init__(self,config_path=DEFAULT_CONFIG):
        self.config_path=Path(config_path).resolve();self.cfg=load_config(self.config_path)
        self.settings=self.cfg['qa']['cover']
        assets=discover_assets(self.cfg,self.config_path.parent,roles=['template_qa','font'])
        self.font_path=assets['font'];self.font_hash=hashlib.sha256(self.font_path.read_bytes()).digest()
        self.font=fitz.Font(fontfile=str(self.font_path));self.templates=fitz.open(assets['template_qa'])
        self.template_bytes=self.templates.tobytes();self.cache={}

    def close(self):self.templates.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def _template(self,kind,index):
        qa=self.cfg['qa'];spec=qa['template_pages']
        if kind not in qa['kinds'] or type(index) is not int or index not in self.cfg['sheet_to_template'].values():
            raise CoverError('QA_TEMPLATE_SELECTION')
        page_index=spec['first']-1+(index-1)*len(qa['kinds'])+qa['kinds'][kind]['template_offset']
        if not spec['first']-1<=page_index<spec['last']:raise CoverError('QA_TEMPLATE_SELECTION')
        if page_index not in self.cache:
            page=self.templates[page_index]
            if page.rotation or page.rect.width>=page.rect.height:raise CoverError('QA_TEMPLATE_ORIENTATION')
            if qa['kinds'][kind]['extracted_title'] not in page.get_text():raise CoverError('QA_TEMPLATE_KIND')
            rows,inner=detect_qa_regions(page,self.cfg)
            baseline=_pixels(page,self.settings['qc_dpi'])
            selected=fitz.open(stream=self.template_bytes,filetype='pdf')
            try:
                intent_kind,intent=selected.xref_get_key(selected.pdf_catalog(),'OutputIntents')
                selected.select([page_index])
                if intent_kind!='null':selected.xref_set_key(selected.pdf_catalog(),'OutputIntents',intent)
                data=selected.tobytes(garbage=4,deflate=True)
            finally:selected.close()
            self.cache[page_index]=(data,rows,baseline)
        return page_index,self.cache[page_index]

    def _story(self,html,size,color,alignment=None):
        rgb=tuple(round(v*255) for v in color)
        css=('@font-face {font-family:qaAria;src:url("'+self.font_path.name+'");}'
             'body,p {margin:0;padding:0;} p {font-family:qaAria;white-space:pre-wrap;direction:rtl;'
             f'font-size:{size:.8f}pt;line-height:{self.settings["line_height"]};'
             'text-align:'+(alignment or self.settings['story_alignment'])+';color:rgb('+','.join(map(str,rgb))+');}')
        return fitz.Story(html='<p id="value" dir="rtl">'+html+'</p>',user_css=css,archive=fitz.Archive(str(self.font_path.parent)))

    def _fit(self,value,row,max_lines,page_rect,last):
        html,formula=render_formula_html(value,settings=self.cfg['qa']['formula'],font=self.font)
        if html is None:html=escape(value)
        for c in value:
            if c.isspace() or unicodedata.category(c) in ('Cc','Cf'):continue
            if formula['formula'] and c in (self.cfg['qa']['formula']['superscript_marker'],self.cfg['qa']['formula']['subscript_marker'],self.cfg['qa']['formula']['opening_brace'],self.cfg['qa']['formula']['closing_brace']):continue
            if not self.font.has_glyph(ord(c),fallback=0):raise FormulaGlyphError('FORMULA_GLYPH_MISSING',c)
        region=fitz.Rect(row['region']);settings=self.settings
        inset=settings['raster_inset_pixels']*72/settings['qc_dpi']
        text_region=fitz.Rect(region.x0+inset,region.y0+inset,region.x1-inset,region.y1-inset)
        scales=[max(settings['min_scale'],1-i*settings['scale_step']) for i in range(math.ceil((1-settings['min_scale'])/settings['scale_step'])+1)]
        for scale in dict.fromkeys(scales):
            size=row['size']*scale
            story=self._story(html,size,row['color'])
            more,filled=story.place(fitz.Rect(0,0,text_region.width,page_rect.height))
            height=fitz.Rect(filled).height;lines=int(round(height/(size*settings['line_height'])))
            if more or not 1<=lines<=max_lines or height>text_region.height:continue
            y=row['origin'][1]-size*settings['baseline_em']
            if lines>1 and not last:y=text_region.y0+(text_region.height-height)/2
            box=fitz.Rect(text_region.x0,y,text_region.x1,y+height+size*settings['guard_em'])
            layer=fitz.open();p=layer.new_page(width=page_rect.width,height=page_rect.height)
            try:
                alignment='left' if row['field']=='topic' else (settings['multiline_alignment'] if lines>1 else settings['story_alignment'])
                spare,applied=p.insert_htmlbox(box,self._story(html,size,row['color'],alignment),scale_low=1)
                if spare<0 or applied!=1:continue
                fonts=p.get_fonts(full=True)
                if not fonts or any(hashlib.sha256(layer.extract_font(f[0])[3]).digest()!=self.font_hash for f in fonts):
                    raise CoverError('QA_FONT_NOT_ARIA')
                gap=word_gap_em(p,size,settings['row_group_em'])
                if gap>settings['max_word_gap_em']:continue
                ink=ink_bbox(p,settings['qc_dpi'])
                if ink is None or not region.contains(ink):continue
                data=layer.tobytes(garbage=4,deflate=True)
                return data,{'value':value,'region':list(region),'ink_bbox':list(ink),'font_size':size,'scale':scale,
                             'lines':lines,'max_lines':max_lines,'alignment':alignment,'max_word_gap_em':gap,'font_embedded':True,'formula':formula,'color':row['color']}
            finally:layer.close()
        raise TextFitError(f'QA_TEXT_DOES_NOT_FIT: {row["field"]}: length={len(value)}: min_scale={settings["min_scale"]}')

    def build(self,kind,template_index,values,page_size_policy=None,*,input_size=None):
        settings=self.settings;policy=page_size_policy or settings['page_size_policy']
        if input_size is not None:
            if len(input_size)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in input_size):
                raise CoverError('QA_INVALID_INPUT_SIZE')
            if input_size[0]>=input_size[1]:raise CoverError('QA_LANDSCAPE_UNSUPPORTED')
        if policy not in ('native','input'):raise CoverError('QA_UNKNOWN_PAGE_POLICY')
        if policy=='input' and input_size is None:raise CoverError('QA_INPUT_SIZE_REQUIRED')
        if set(values)!=set(settings['fields']):raise CoverError('QA_EXPECTED_THREE_FIELDS')
        if all(is_empty_value(v) for v in values.values()):raise CoverError('EMPTY_SYLLABUS_RECORD')
        if any(not is_empty_value(v) and not isinstance(v,str) for v in values.values()):raise CoverError('INVALID_SYLLABUS_VALUE')
        page_index,(data,rows,baseline)=self._template(kind,template_index)
        result=fitz.open(stream=data,filetype='pdf');reports={}
        try:
            page=result[0]
            for index,row in enumerate(rows):
                value=values[row['field']]
                page.draw_rect(fitz.Rect(row['placeholder']),color=None,fill=settings['erase_color'],overlay=True)
                if is_empty_value(value):reports[row['field']]={'value':value,'empty':True,'placeholder_erased':True,'region':row['region']};continue
                layer,report=self._fit(value,row,settings['max_lines'][index],page.rect,index==len(rows)-1)
                with fitz.open(stream=layer,filetype='pdf') as overlay:page.show_pdf_page(page.rect,overlay,0)
                reports[row['field']]=dict(report,empty=False,placeholder_erased=True)
            actual=_pixels(page,settings['qc_dpi'])
            allowed=np.zeros(baseline.shape[:2],dtype=bool)
            factor=settings['qc_dpi']/72
            for row in rows:
                x0,y0,x1,y1=(fitz.Rect(row['region'])*factor).irect
                allowed[y0:y1,x0:x1]=True
            changed=np.any(actual!=baseline,axis=2)
            outside=int(np.count_nonzero(changed & ~allowed))
            if outside:raise CoverError(f'QA_PIXELS_OUTSIDE_VALUES: {outside}')
            report={'kind':kind,'template_index':template_index,'template_page':page_index+1,
                           'page_size_policy':policy,'page_size':[page.rect.width,page.rect.height],'fields':reports,
                           'pixel_qc':{'dpi':settings['qc_dpi'],'changed_pixels':int(changed.sum()),'outside_values':outside}}
            if policy=='input':
                adapted,report=self._input_cover(result,data,report,input_size)
                result.close()
                return adapted,report
            return result,report
        except Exception:result.close();raise

    def _input_cover(self,native,blank_data,report,size):
        from frame import QAFrame
        from pages import _preserve_rendering_attributes
        frame=QAFrame(self.config_path)
        rect=fitz.Rect(0,0,*size)
        native_rect=native[0].rect
        dx,dy=(rect.width-native_rect.width)/2,(rect.height-native_rect.height)/2
        shift=fitz.Matrix(1,0,0,1,dx,dy)
        clip=frame.inner_rect(native_rect)
        inset=self.settings['raster_inset_pixels']*72/self.settings['qc_dpi']
        clip=fitz.Rect(clip.x0+inset,clip.y0+inset,clip.x1-inset,clip.y1-inset)
        safe=frame.inner_rect(rect)

        def frameless(source):
            clean=fitz.open(stream=source.tobytes(),filetype='pdf')
            strokes=[p for p in clean[0].get_drawings() if p['type']=='s']
            if len(strokes)!=len(frame.segments):
                clean.close();raise CoverError('QA_FRAME_REMOVAL_GEOMETRY')
            for path in strokes:
                r=fitz.Rect(path['rect']);pad=path['width']/2+frame.tolerance
                clean[0].add_redact_annot(fitz.Rect(r.x0-pad,r.y0-pad,r.x1+pad,r.y1+pad),fill=False,cross_out=False)
            clean[0].apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,text=fitz.PDF_REDACT_TEXT_NONE)
            if any(p['type']=='s' for p in clean[0].get_drawings()):
                clean.close();raise CoverError('QA_FRAME_REMOVAL_FAILED')
            return clean

        def adapt(source):
            # Check the whole source interior before drawing to a smaller page;
            # a destination clip must never conceal lost logo, labels or text.
            with fitz.open() as interior:
                p=interior.new_page(width=native_rect.width,height=native_rect.height)
                p.show_pdf_page(clip,source,0,clip=clip)
                _preserve_rendering_attributes(source,interior)
                pixels=_pixels(p,self.settings['qc_dpi'])
                ys,xs=np.where(np.any(pixels!=255,axis=2))
                if len(xs):
                    factor=72/self.settings['qc_dpi']
                    ink=fitz.Rect(xs.min()*factor,ys.min()*factor,(xs.max()+1)*factor,(ys.max()+1)*factor)*shift
                    if not safe.contains(ink):raise CoverError('QA_INPUT_COVER_CLIP_UNSAFE')
            target=fitz.open()
            try:
                p=target.new_page(width=rect.width,height=rect.height)
                p.show_pdf_page(clip*shift,source,0,clip=clip,keep_proportion=True)
                _preserve_rendering_attributes(source,target)
                frame.apply(p)
                # Reload after grafting OutputIntents: MuPDF may otherwise keep
                # the pre-graft color cache until the first on-disk reopening.
                reopened=fitz.open(stream=target.tobytes(),filetype='pdf')
                target.close()
                return reopened
            except Exception:target.close();raise

        with frameless(native) as clean:
            adapted=adapt(clean)
        try:
            with fitz.open(stream=blank_data,filetype='pdf') as blank:
                with frameless(blank) as clean:
                    reference=adapt(clean)
                try:baseline=_pixels(reference[0],self.settings['qc_dpi'])
                finally:reference.close()
            final=copy.deepcopy(report)
            final.update(page_size=list(size),native_page_size=list(native_rect[2:]),
                         content_transform=list(shift),source_clip=list(clip),frame_bbox=list(safe))
            allowed=np.zeros(baseline.shape[:2],dtype=bool)
            for info in final['fields'].values():
                for key in ('region','ink_bbox'):
                    if key in info:info[key]=list(fitz.Rect(info[key])*shift)
                x0,y0,x1,y1=(fitz.Rect(info['region'])*(self.settings['qc_dpi']/72)).irect
                allowed[max(0,y0):min(allowed.shape[0],y1),max(0,x0):min(allowed.shape[1],x1)]=True
            changed=np.any(_pixels(adapted[0],self.settings['qc_dpi'])!=baseline,axis=2)
            outside=int(np.count_nonzero(changed & ~allowed))
            if outside:raise CoverError(f'QA_PIXELS_OUTSIDE_VALUES: {outside}')
            final['native_pixel_qc']=report['pixel_qc']
            final['pixel_qc']={'dpi':self.settings['qc_dpi'],'changed_pixels':int(changed.sum()),'outside_values':outside}
            return adapted,final
        except Exception:adapted.close();raise


def build_qa_cover(kind,template_index,values,page_size_policy=None,*,input_size=None,config_path=DEFAULT_CONFIG):
    with QACoverBuilder(config_path) as builder:
        return builder.build(kind,template_index,values,page_size_policy,input_size=input_size)
