"""Step 3b stop gate: baking must preserve every rendered pixel, with no border.

Run: python -m pytest tests/test_bake.py -q
Diagnostics only; never saves or applies a baked PDF to the production pipeline.
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz
import pytest
from syllabus import load_config, discover_assets
from pages import raster, _preserve_rendering_attributes

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()


@pytest.fixture(scope='module')
def bake_evidence():
    assets = discover_assets(CFG, ROOT)
    debug = ROOT / CFG['paths']['debug']
    records = []
    for path in sorted((ROOT / CFG['paths']['input']).glob('*.pdf')):
        with fitz.open(path) as original, fitz.open() as trial:
            trial.insert_pdf(original)
            _preserve_rendering_attributes(original, trial)
            before = [raster(p, CFG['pages']['diagnostic_dpi']) for p in trial]
            annotations = [len(list(p.annots() or [])) for p in trial]
            widgets = [len(list(p.widgets() or [])) for p in trial]
            # User-authorized operation only. No correction or fallback afterwards.
            trial.bake(annots=True, widgets=False)
            for index, (page, old) in enumerate(zip(trial, before)):
                new = raster(page, CFG['pages']['diagnostic_dpi'])
                delta = np.abs(new.astype(np.int16)-old.astype(np.int16))
                changed = np.any(delta != 0, axis=2)
                ys,xs = np.nonzero(changed)
                entry = {'source': path.name, 'page': index+1,
                         'annotations_before': annotations[index],
                         'annotations_after': len(list(page.annots() or [])),
                         'widgets_before': widgets[index],
                         'widgets_after': len(list(page.widgets() or [])),
                         'different_pixels': int(changed.sum()),
                         'max_channel_difference': int(delta.max()),
                         'difference_bbox_pixels': [int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)] if len(xs) else None}
                if len(xs):
                    # Exact raster pixels, with a small diagnostic margin only.
                    x0,y0,x1,y1=entry['difference_bbox_pixels']
                    x0,y0=max(0,x0-12),max(0,y0-12)
                    x1,y1=min(old.shape[1],x1+12),min(old.shape[0],y1+12)
                    old_crop=Image.fromarray(old[y0:y1,x0:x1])
                    new_crop=Image.fromarray(new[y0:y1,x0:x1])
                    diff=np.full_like(old[y0:y1,x0:x1],255)
                    diff[changed[y0:y1,x0:x1]]=[255,0,0]
                    canvas=Image.new('RGB',(old_crop.width*3,old_crop.height+25),'white')
                    for j,img in enumerate((old_crop,new_crop,Image.fromarray(diff))):
                        canvas.paste(img,(j*old_crop.width,25))
                    ImageDraw.Draw(canvas).text((5,5),'BEFORE / AFTER BAKE / EXACT DIFFERENCE (RED)',fill='black')
                    filename=f'bake_{path.stem.replace(" ","_")}_p{index+1}.png'
                    canvas.save(debug/filename)
                    entry['image']=filename
                records.append(entry)
    result={'dpi':CFG['pages']['diagnostic_dpi'], 'pymupdf_version':fitz.VersionBind,
            'asset_matches':{k:v.relative_to(ROOT).as_posix() for k,v in assets.items()},
            'operation':{'annots':True,'widgets':False},'pages':records}
    (debug/'bake_step3b.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return records


@pytest.mark.parametrize('index',range(24))
def test_bake_pixel_identity(bake_evidence,index):
    entry=bake_evidence[index]
    assert entry['widgets_before']==entry['widgets_after']
    assert entry['annotations_after']==0
    assert entry['different_pixels']==0, entry
