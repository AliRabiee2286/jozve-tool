"""Rebuild local Q6 visual evidence; never publish these as final-QC output."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import pymupdf as fitz
from PIL import Image
from qa_pages import process_qa_pages
from qa_cover import QACoverBuilder
from syllabus import Syllabus
from qa_cover_sweep import records


def write_case(name,source,destination):
    source[0].get_pixmap(dpi=150).save(destination/(name+'_before.png'))
    out,report=process_qa_pages(source)
    try:
        out.save(destination/(name+'_after.pdf'))
        image_path=destination/(name+'_after.png')
        out[0].get_pixmap(dpi=150).save(image_path)
        im=Image.open(image_path)
        edge=round(min(im.size)*.15)
        corners=Image.new('RGB',(edge*2,edge*2),'white')
        for box,xy in [((0,0,edge,edge),(0,0)),((im.width-edge,0,im.width,edge),(edge,0)),
                       ((0,im.height-edge,edge,im.height),(0,edge)),
                       ((im.width-edge,im.height-edge,im.width,im.height),(edge,edge))]:
            corners.paste(im.crop(box),xy)
        corners.resize((edge*4,edge*4)).save(destination/(name+'_corners.png'))
        (destination/(name+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:out.close()


def main():
    dest=ROOT/'debug/qa_pages';dest.mkdir(exist_ok=True)
    rows=records(Syllabus(ROOT/'config.yaml'))
    with QACoverBuilder() as builder:
        for path in sorted((ROOT/'tests/data/qa').glob('*.pdf')):
            with fitz.open(path) as source:
                write_case(path.stem,source,dest)
                kind='pasokh' if path.stem.endswith('_pasokh') else 'soal'
                row=next(r for r in rows if r['namak']=='shimi_physic_20_'+kind)
                values={f:row[f] for f in builder.settings['fields']}
                cover,report=builder.build(kind,row['template_index'],values,input_size=(source[0].rect.width,source[0].rect.height))
                try:
                    cover.save(dest/(kind+'_cover_a4.pdf'))
                    cover[0].get_pixmap(dpi=150).save(dest/(kind+'_cover_a4.png'))
                    (dest/(kind+'_cover_a4.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                finally:cover.close()
    for name,width,height,rotation in [('landscape',842,595,0),('rotation90',595,842,90)]:
        with fitz.open() as source:
            p=source.new_page(width=width,height=height)
            p.draw_rect(fitz.Rect(10,110,40,180),fill=(0,0,0))
            p.insert_text((100,100),'Vector content - fixed-width frame',fontsize=16)
            p.set_rotation(rotation)
            write_case(name,source,dest)
    print('Q6 evidence: debug/qa_pages (content pages and separate A4 covers; no final Q7 QC)')


if __name__=='__main__':main()
