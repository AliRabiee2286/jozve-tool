"""Independent sample measurements and real-content 50-page benchmark."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from syllabus import load_config, discover_assets, Syllabus
from naamak import resolve, to_output_name

CFG=load_config(); OUT=ROOT/CFG['paths']['output']/'step5'
DEBUG=ROOT/CFG['paths']['debug']/'step5'; DEBUG.mkdir(parents=True,exist_ok=True)
DATA=ROOT/'tests/data/step5'; DATA.mkdir(parents=True,exist_ok=True)


def hashes():
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for role in ('input','assets','samples') for p in (ROOT/CFG['paths'][role]).iterdir() if p.is_file()}


def execute(args):
    start=time.perf_counter()
    run=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'main.py'),*map(str,args)],cwd=ROOT,capture_output=True,timeout=3600)
    return {'seconds':time.perf_counter()-start,'returncode':run.returncode,
            'stdout':run.stdout.decode('utf-8',errors='replace'),'stderr':run.stderr.decode('utf-8',errors='replace')}


def raster(page,dpi=80):
    p=page.get_pixmap(dpi=dpi,alpha=False)
    return np.frombuffer(p.samples,dtype=np.uint8).reshape(p.height,p.width,3).copy()


def compare():
    before=hashes()
    assets=discover_assets(CFG,ROOT)
    evidence={'assets':{k:p.relative_to(ROOT).as_posix() for k,p in assets.items()},'source_hashes_before':before}
    evidence['run']=execute(['--output',OUT])
    if evidence['run']['returncode']:
        (DEBUG/'audit.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        raise AssertionError(evidence['run'])
    report=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    evidence['files']=len(report['items']);evidence['all_qc']=all(i['qc']['passed'] for i in report['items'])
    historical=json.loads((ROOT/'tests/data/inspection_evidence.json').read_text(encoding='utf-8'))['source_hashes_before']
    syll=Syllabus(); comparisons=[]; panels=[]
    for source in sorted((ROOT/CFG['paths']['input']).glob('*.pdf')):
        if source.relative_to(ROOT).as_posix() not in historical:continue
        namak=resolve(source.name,syll);name=to_output_name(namak)
        with fitz.open(source) as raw,fitz.open(OUT/name) as ours,fitz.open(ROOT/CFG['paths']['samples']/name) as sample:
            record={'namak':namak,'input_pages':len(raw),'output_pages':len(ours),'sample_pages':len(sample),'pages':[]}
            assert len(ours)==len(raw)+1==len(sample)
            for n,(a,b) in enumerate(zip(ours,sample)):
                ga=list(a.rect);gb=list(b.rect)
                same=ga==gb;orientation=(a.rect.width>a.rect.height)==(b.rect.width>b.rect.height)
                if n:
                    assert a.rect==raw[n-1].rect and a.rotation==raw[n-1].rotation
                assert orientation
                x,y=raster(a),raster(b)
                metric={'page':n+1,'ours_size':ga,'sample_size':gb,'same_size':same,'same_orientation':orientation,
                        'ours_rotation':a.rotation,'sample_rotation':b.rotation}
                if x.shape==y.shape:
                    d=np.abs(x.astype('int16')-y.astype('int16'))
                    metric.update(different_percent=float(np.any(d,axis=2).mean()*100),mean_channel_difference=float(d.mean()),max_channel_difference=int(d.max()))
                else: metric['different_percent']=None
                record['pages'].append(metric)
                left=Image.fromarray(x);right=Image.fromarray(y)
                for im in (left,right):im.thumbnail((430,580))
                panel=Image.new('RGB',(880,620),'white');panel.paste(left,(5,30));panel.paste(right,(445,30))
                ImageDraw.Draw(panel).text((5,5),f'{namak} / p{n+1}: GENERATED | SAMPLE',fill='black')
                panels.append(panel)
                if n==0:panel.save(DEBUG/f'cover_{namak.replace(" ","_")}.png')
            comparisons.append(record)
    for offset in range(0,len(panels),4):
        sheet=Image.new('RGB',(1760,1240),'white')
        for j,panel in enumerate(panels[offset:offset+4]):sheet.paste(panel,((j%2)*880,(j//2)*620))
        sheet.save(DEBUG/f'comparison_{offset//4+1:02}.png')
    evidence.update(comparisons=comparisons,source_hashes_unchanged=before==hashes(),comparison_pages=len(panels))
    (DEBUG/'audit.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    assert evidence['all_qc'] and evidence['source_hashes_unchanged']
    print('comparison complete',evidence['files'],len(panels),flush=True)


def benchmark():
    syll=Syllabus()
    source=next(p for p in (ROOT/CFG['paths']['input']).glob('*.pdf') if resolve(p.name,syll)=='physics_thermo_8')
    directory=DATA/'benchmark';directory.mkdir(exist_ok=True)
    path=directory/source.name
    with fitz.open(source) as raw,fitz.open() as doc:
        for i in range(50):doc.insert_pdf(raw,from_page=i%len(raw),to_page=i%len(raw))
        doc.save(path,garbage=4,deflate=True)
    result=execute(['--input',path,'--output',OUT/'benchmark'])
    result.update(input_pages=50,input_bytes=path.stat().st_size,construction='Cycle through all five physics_thermo_8 content pages ten times; vector copy')
    report=json.loads((OUT/'benchmark/report.json').read_text(encoding='utf-8'))['items'][0]
    result.update(status=report['status'],qc=report.get('qc',{}).get('passed'),output_pages=report.get('output_pages'),seconds_per_page=result['seconds']/50)
    (DEBUG/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['returncode']==0 and result['qc'] and result['output_pages']==51,result
    print('benchmark complete',result['seconds'],flush=True)


if __name__=='__main__':
    if '--benchmark' in sys.argv:benchmark()
    else:compare()
