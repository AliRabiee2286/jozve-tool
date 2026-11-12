"""Read-only QA source validation; no production rendering or baseline changes."""
import json
import sys
from pathlib import Path
import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from syllabus import discover_assets, load_config, normalize_key


def inspect_assets(cfg, root=ROOT):
    assets = discover_assets(cfg, root, roles=list(cfg['asset_patterns']))
    assert len(set(assets.values())) == len(assets), 'Asset patterns overlap'
    qa = cfg['qa']; spec = qa['template_pages']; rules = qa['asset_validation']
    kinds = sorted(qa['kinds'].items(), key=lambda item: item[1]['template_offset'])
    assert [v['template_offset'] for _, v in kinds] == list(range(len(kinds)))
    count = spec['last'] - spec['first'] + 1
    assert count == len(cfg['sheet_to_template']) * len(kinds)
    pages = []; comparisons = []
    with fitz.open(assets['template_qa']) as doc, fitz.open(assets['template']) as old:
        assert len(doc) == spec['total'] == spec['last']
        assert len(old) == spec['first'] - 1
        for index in range(spec['first'] - 1, spec['last']):
            page = doc[index]; kind, definition = kinds[(index - spec['first'] + 1) % len(kinds)]
            assert page.rotation == 0 and page.rect.width < page.rect.height
            assert all(abs(a-b) <= spec['tolerance'] for a,b in zip((page.rect.width,page.rect.height),spec['size']))
            text = page.get_text()
            assert definition['extracted_title'] in text, (index+1, kind, text)
            for other, other_definition in kinds:
                if other != kind:
                    assert other_definition['extracted_title'] not in text
            assert text.count(qa['cover']['placeholder']) == len(qa['cover']['fields'])
            labels = [normalize_key(line.split(':')[-1]) for line in text.splitlines() if ':' in line]
            assert len(labels) == len(qa['cover']['fields'])
            for field in qa['cover']['fields']:
                aliases = {normalize_key(v) for v in cfg['headers'][field]}
                assert sum(label in aliases for label in labels) == 1, (index+1, field, labels)
            pages.append({'page':index+1, 'kind':kind, 'text':text})
        for index in range(len(old)):
            a=old[index].get_pixmap(dpi=spec['comparison_dpi'], alpha=False)
            b=doc[index].get_pixmap(dpi=spec['comparison_dpi'], alpha=False)
            same=(a.width,a.height,a.n,a.samples)==(b.width,b.height,b.n,b.samples)
            comparisons.append({'page':index+1,'identical':same})
    geometry=[]
    with fitz.open(assets['frame_qa']) as doc:
        assert len(doc)==rules['frame_pages']
        page=doc[0]
        assert not page.get_text().strip() and not page.get_images()
        assert all(abs(a-b)<=spec['tolerance'] for a,b in zip((page.rect.width,page.rect.height),spec['size']))
        drawings=page.get_drawings()
        assert len(drawings)==rules['frame_segments']
        for drawing in drawings:
            assert drawing['type']=='s' and len(drawing['items'])==1
            command,a,b=drawing['items'][0]
            assert command=='l'
            horizontal=abs(a.y-b.y)<=spec['tolerance']
            vertical=abs(a.x-b.x)<=spec['tolerance']
            assert horizontal != vertical
            if horizontal:
                edge='top' if a.y<page.rect.height/2 else 'bottom'
                distance=a.y if edge=='top' else page.rect.height-a.y
            else:
                edge='left' if a.x<page.rect.width/2 else 'right'
                distance=a.x if edge=='left' else page.rect.width-a.x
            geometry.append({'edge':edge,'distance':distance,'start':list(a),'end':list(b),
                             'width':drawing['width'],'color':list(drawing['color'])})
        assert len({tuple(g['color']) for g in geometry})==rules['frame_colors']
        widths={g['width'] for g in geometry}
        assert len(widths)==rules['frame_widths'] and min(widths)>0
        for width in widths:
            assert sorted(g['edge'] for g in geometry if g['width']==width)==sorted(['top','bottom','left','right'])
    return {'qa_pages':pages,'frame_geometry':geometry,'legacy_comparison':comparisons}


if __name__=='__main__':
    result=inspect_assets(load_config(ROOT/'config.yaml'))
    target=ROOT/'cache/q1_assets.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'qa_pages':len(result['qa_pages']),'legacy_identical':sum(v['identical'] for v in result['legacy_comparison']), 'frame_geometry':result['frame_geometry']},ensure_ascii=False))
