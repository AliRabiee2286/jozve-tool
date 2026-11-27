"""Real Story/raster proof for Q4, independent of production cover generation."""
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from formula import render_formula_html
from syllabus import load_config,discover_assets


def render(fragment,cfg,font_path,*,direction='ltr',colors=False):
    proof=cfg['qa']['formula']['proof']
    css=('@font-face {font-family: formulaAria; src:url("'+font_path.name+'");}'
         'body {margin:0;padding:0;} p {margin:0;padding:0;font-family:formulaAria;'
         f'font-size:{proof["font_size"]}pt;line-height:{proof["line_height"]};'
         'white-space:pre-wrap;direction:'+direction+';text-align:'+('right' if direction=='rtl' else 'left')+';'
         'color:'+(proof['base_color'] if colors else proof['text_color'])+';}')
    if colors:css+='sup,sub,.script {color:'+proof['script_color']+';}'
    story=fitz.Story(html='<p dir="'+direction+'">'+fragment+'</p>',user_css=css,archive=fitz.Archive(str(font_path.parent)))
    doc=fitz.open();page=doc.new_page(width=proof['page_size'][0],height=proof['page_size'][1])
    box=fitz.Rect(page.rect);box.x0+=proof['margin'];box.y0+=proof['margin'];box.x1-=proof['margin'];box.y1-=proof['margin']
    spare,scale=page.insert_htmlbox(box,story,scale_low=1)
    assert spare>=0 and scale==1, 'Proof did not fit without scaling'
    expected=hashlib.sha256(font_path.read_bytes()).digest()
    fonts=page.get_fonts(full=True)
    assert fonts and all(hashlib.sha256(doc.extract_font(f[0])[3]).digest()==expected for f in fonts), 'Non-Aria font in Story output'
    pix=page.get_pixmap(dpi=proof['dpi'],alpha=False)
    pixels=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n).copy()
    return doc,pix,pixels


def script_bounds(pixels,color):
    channels=[int(color.lstrip('#')[i:i+2],16) for i in range(0,6,2)]
    dominant=int(np.argmax(channels))
    assert channels.count(max(channels))==1, 'Proof script color must have one dominant channel'
    others=[i for i in range(3) if i!=dominant]
    mask=np.all(pixels[:,:,dominant,None]>pixels[:,:,others],axis=2)
    y,x=np.nonzero(mask)
    assert len(x), 'No script ink'
    return [int(x.min()),int(y.min()),int(x.max()+1),int(y.max()+1)]


def make_proof(output=None):
    cfg=load_config(ROOT/'config.yaml');font_path=discover_assets(cfg,ROOT,roles=['font'])['font']
    settings=cfg['qa']['formula'];font=fitz.Font(fontfile=str(font_path))
    examples={'superscript':render_formula_html('e^x',settings=settings,font=font)[0],
              'sup_plain':'e<span class="script">x</span>',
              'subscript':render_formula_html('x_{1}',settings=settings,font=font)[0],
              'sub_plain':'x<span class="script">1</span>'}
    boxes={}
    if output:output.mkdir(parents=True,exist_ok=True)
    for name,html in examples.items():
        doc,pix,pixels=render(html,cfg,font_path,colors=True)
        try:
            boxes[name]=script_bounds(pixels,settings['proof']['script_color'])
            if output:pix.save(output/(name+'.png'))
        finally:doc.close()
    # Same glyph, font, page and line origin: compare raster ink, not decoded text.
    assert boxes['superscript'][1]<boxes['sup_plain'][1]
    assert boxes['superscript'][3]<boxes['sup_plain'][3]
    assert boxes['subscript'][3]>boxes['sub_plain'][3]
    sample='توابع In وe^x، حل معادلات لگاریتمی'
    html,report=render_formula_html(sample,settings=settings,font=font)
    doc,pix,pixels=render(html,cfg,font_path,direction='rtl')
    try:
        if output:
            pix.save(output/'persian_formula.png')
            doc.save(output/'persian_formula.pdf')
    finally:doc.close()
    result={'dpi':settings['proof']['dpi'],'script_ink_pixels':boxes,
            'aria_only':True,'input':sample,'html':html,'report':report}
    if output:(output/'proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    print(json.dumps(make_proof(ROOT/'debug/formula'),ensure_ascii=False))
