"""Native QA covers only. Legacy cover renderer and content pages are untouched."""
from html import escape
from pathlib import Path
import hashlib
import math
import unicodedata
import numpy as np
import pymupdf as fitz
from cover import CoverError, TextFitError, ink_bbox
from formula import render_formula_html, FormulaGlyphError
from syllabus import DEFAULT_CONFIG, load_config, discover_assets, normalize_key, is_empty_value


def _pixels(page,dpi):
    pix=page.get_pixmap(dpi=dpi,alpha=False)
    return np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n).copy()


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

    def _story(self,html,size,color):
        rgb=tuple(round(v*255) for v in color)
        css=('@font-face {font-family:qaAria;src:url("'+self.font_path.name+'");}'
             'body,p {margin:0;padding:0;} p {font-family:qaAria;white-space:pre-wrap;direction:rtl;'
             f'font-size:{size:.8f}pt;line-height:{self.settings["line_height"]};'
             'text-align:'+self.settings['story_alignment']+';color:rgb('+','.join(map(str,rgb))+');}')
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
                spare,applied=p.insert_htmlbox(box,self._story(html,size,row['color']),scale_low=1)
                if spare<0 or applied!=1:continue
                fonts=p.get_fonts(full=True)
                if not fonts or any(hashlib.sha256(layer.extract_font(f[0])[3]).digest()!=self.font_hash for f in fonts):
                    raise CoverError('QA_FONT_NOT_ARIA')
                ink=ink_bbox(p,settings['qc_dpi'])
                if ink is None or not region.contains(ink):continue
                data=layer.tobytes(garbage=4,deflate=True)
                return data,{'value':value,'region':list(region),'ink_bbox':list(ink),'font_size':size,'scale':scale,
                             'lines':lines,'max_lines':max_lines,'font_embedded':True,'formula':formula,'color':row['color']}
            finally:layer.close()
        raise TextFitError(f'QA_TEXT_DOES_NOT_FIT: {row["field"]}: length={len(value)}: min_scale={settings["min_scale"]}')

    def build(self,kind,template_index,values,page_size_policy=None,*,input_size=None):
        settings=self.settings;policy=page_size_policy or settings['page_size_policy']
        if input_size is not None and input_size[0]>=input_size[1]:raise CoverError('QA_LANDSCAPE_UNSUPPORTED')
        if policy!='native':raise CoverError('QA_INPUT_POLICY_PENDING_Q6' if policy=='input' else 'QA_UNKNOWN_PAGE_POLICY')
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
            return result,{'kind':kind,'template_index':template_index,'template_page':page_index+1,
                           'page_size_policy':policy,'page_size':[page.rect.width,page.rect.height],'fields':reports,
                           'pixel_qc':{'dpi':settings['qc_dpi'],'changed_pixels':int(changed.sum()),'outside_values':outside}}
        except Exception:result.close();raise


def build_qa_cover(kind,template_index,values,page_size_policy=None,*,input_size=None,config_path=DEFAULT_CONFIG):
    with QACoverBuilder(config_path) as builder:
        return builder.build(kind,template_index,values,page_size_policy,input_size=input_size)
