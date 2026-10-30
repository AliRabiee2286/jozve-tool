"""Experimental reference-only assembly; production modules are never edited."""
from pathlib import Path
import json
import runpy
import sys
import numpy as np
import pymupdf as fitz
from PIL import Image,ImageDraw
from syllabus import load_config,discover_assets
from border import placements
from pages import fit_content,remove_numbers,_preserve_rendering_attributes,raster


def main():
    root=Path(__file__).resolve().parents[1];cfg=load_config();assets=discover_assets(cfg,root)
    sys.path.insert(0,str(root/'tests'))
    render=runpy.run_path(str(root/'tests/test_fit.py'))['render_direct']
    assemble=runpy.run_path(str(root/'tests/fit_reference.py'))['assemble_reference']
    rows=[]
    for name in ('ai_par_2','shimi_alee_7'):
        with fitz.open(root/cfg['paths']['input']/(name+'.pdf')) as src,fitz.open() as base,fitz.open() as out,fitz.open(assets['border']) as border:
            base.insert_pdf(src);_preserve_rendering_attributes(src,base);base.bake(annots=True,widgets=False)
            for p in base:remove_numbers(p,cfg['pages'])
            out.insert_pdf(base);_preserve_rendering_attributes(base,out)
            for p,q in zip(base,out):
                pieces=placements(p.rect,border[0].rect,cfg['border'])
                fit=fit_content(q,pieces,cfg['pages'])
                a=raster(q,150)
                independent,geometry=assemble(p,pieces,cfg['pages'])
                with independent:
                    reference_pixels=raster(independent[p.number],150)
                    difference=np.abs(a.astype(np.int16)-reference_pixels.astype(np.int16))
                    independent_metrics={'independent_max':int(difference.max()),'independent_pixels':int(np.any(difference,axis=2).sum())}
                    if p.number==0 or (name=='ai_par_2' and p.number==2):
                        images=[Image.fromarray(pixels) for pixels in (reference_pixels,a)]
                        for im in images:im.thumbnail((850,1100))
                        canvas=Image.new('RGB',(sum(im.width for im in images),max(im.height for im in images)+30),'white')
                        x=0
                        for im in images:canvas.paste(im,(x,30));x+=im.width
                        ImageDraw.Draw(canvas).text((5,5),'SOURCE REFERENCE / FITTED - different pixels: '+str(independent_metrics['independent_pixels']),fill='black')
                        canvas.save(root/cfg['paths']['debug']/f'step4b_fit_verified_{name}_p{p.number+1}.png')
                with fitz.open(stream=base.tobytes(),filetype='pdf') as ref:
                    r=ref[p.number];ref.xref_set_key(r.xref,'Contents','[]')
                    r.show_pdf_page(fitz.Rect(fit['content_bbox']),base,p.number)
                    b=raster(r,150)
                    delta=np.abs(a.astype(np.int16)-b.astype(np.int16))
                    rows.append({'source':name,'page':p.number+1,'show_pdf_page_max':int(delta.max()),'show_pdf_page_pixels':int(np.any(delta,axis=2).sum()),**independent_metrics})
    (root/'output/step4b_fit_reference_probe.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print(rows)


if __name__=='__main__':main()
