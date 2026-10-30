"""Read-only diagnostic for newly exposed fit-render differences; no tolerance changes."""
import json
import runpy
import sys
from pathlib import Path
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw
from syllabus import load_config,discover_assets
from pages import remove_numbers,fit_content,_preserve_rendering_attributes
from border import placements


def split_render(page, page_matrix, device_matrix, width, height):
    pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,width,height),False);pix.clear_with(255)
    dev=fitz.mupdf.fz_new_draw_device(fitz.JM_matrix_from_py(device_matrix),pix.this)
    fitz.mupdf.fz_run_page(page.this,dev,fitz.JM_matrix_from_py(page_matrix),fitz.mupdf.FzCookie())
    fitz.mupdf.fz_close_device(dev)
    return np.frombuffer(pix.samples,np.uint8).reshape(height,width,3).copy()


def main():
    root=Path(__file__).resolve().parents[1];cfg=load_config();assets=discover_assets(cfg,root)
    sys.path.insert(0,str(root/'tests'))
    render=runpy.run_path(str(root/'tests/test_fit.py'))['render_direct']
    rows=[]
    for name in ('ai_par_2','shimi_alee_7'):
        with fitz.open(root/cfg['paths']['input']/(name+'.pdf')) as src,fitz.open() as base,fitz.open() as fitted,fitz.open(assets['border']) as border:
            base.insert_pdf(src);_preserve_rendering_attributes(src,base);base.bake(annots=True,widgets=False)
            for p in base: remove_numbers(p,cfg['pages'])
            fitted.insert_pdf(base);_preserve_rendering_attributes(base,fitted)
            for p,q in zip(base,fitted):
                info=fit_content(q,placements(q.rect,border[0].rect,cfg['border']),cfg['pages'])
                zoom=fitz.Matrix(150/72,150/72);box=(q.rect*zoom).irect
                old=render(p,fitz.Matrix(info['display_matrix'])*zoom,box.width,box.height)
                actual=render(q,zoom,box.width,box.height)
                # Diagnostic only: avoid the reference's intermediate float32
                # matrix multiplication. Production geometry remains untouched.
                alternative=render(p,fitz.Matrix(*(v*(150/72) for v in info['display_matrix'])),box.width,box.height)
                diff=np.abs(old.astype(np.int16)-actual.astype(np.int16));changed=np.any(diff,axis=2)
                alt=np.abs(alternative.astype(np.int16)-actual.astype(np.int16))
                split_before=split_render(p,fitz.Matrix(info['display_matrix']),zoom,box.width,box.height)
                split_after=split_render(q,fitz.Identity,zoom,box.width,box.height)
                split_diff=np.abs(split_before.astype(np.int16)-split_after.astype(np.int16))
                row={'source':name,'page':p.number+1,'max_channel_difference':int(diff.max()),
                    'different_pixels':int(changed.sum()),'float64_reference_max':int(alt.max()),
                    'float64_reference_different_pixels':int(np.any(alt,axis=2).sum()),
                    'split_device_max':int(split_diff.max()),'split_device_pixels':int(np.any(split_diff,axis=2).sum()),'fit':info}
                if changed.any():
                    ys,xs=np.nonzero(changed);x0=max(0,int(xs.min())-10);x1=min(box.width,int(xs.max())+11)
                    y0=max(0,int(ys.min())-10);y1=min(box.height,int(ys.max())+11)
                    row['difference_bbox_pixels']=[x0,y0,x1,y1]
                    row['exact_difference_bbox_pixels']=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
                    row['dpi']=150
                    row['output_intents_before']=base.xref_get_key(base.pdf_catalog(),'OutputIntents')
                    row['output_intents_after']=fitted.xref_get_key(fitted.pdf_catalog(),'OutputIntents')
                    parts=[Image.fromarray(im[y0:y1,x0:x1]) for im in (old,actual)]
                    canvas=Image.new('RGB',(parts[0].width*2,parts[0].height+25),'white')
                    for j,im in enumerate(parts): canvas.paste(im,(j*im.width,25))
                    ImageDraw.Draw(canvas).text((5,5),'DIRECT REFERENCE / FITTED (NO BORDER)',fill='black')
                    canvas.save(root/cfg['paths']['debug']/f'step4b_fit_difference_{name}_p{p.number+1}.png')
                rows.append(row)
    (root/cfg['paths']['output']/'step4b_fit_diagnostic.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print([{k:v for k,v in r.items() if k not in ('fit','difference_bbox_pixels')} for r in rows])


if __name__=='__main__': main()
