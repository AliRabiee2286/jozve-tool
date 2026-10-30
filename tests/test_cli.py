"""Steps 4/4b: thirteen-file acceptance and Windows/error-path contracts."""
import json
from pathlib import Path
import subprocess
import sys
import hashlib
import pymupdf as fitz
import pytest
import main as app
from syllabus import load_config, Syllabus
from naamak import to_output_name, resolve
from border import clean_border
from pages import process_pages

ROOT=Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run([sys.executable,'-X','utf8',str(ROOT/'main.py'),*map(str,args)],cwd=ROOT,
                          capture_output=True,text=True,encoding='utf-8',timeout=1800)


def make_pdf(path,text='vector',size=(600,800)):
    path.parent.mkdir(parents=True,exist_ok=True)
    with fitz.open() as doc:
        p=doc.new_page(width=size[0],height=size[1]);p.insert_text((80,100),text)
        doc.save(path)


def test_thirteen_real_inputs_and_overwrite():
    cfg=load_config();syll=Syllabus();sources=sorted((ROOT/cfg['paths']['input']).glob('*.pdf'))
    assert len(sources)==13
    before={p:hashlib.sha256(p.read_bytes()).hexdigest() for directory in ('input','assets','samples') for p in (ROOT/cfg['paths'][directory]).iterdir() if p.is_file()}
    names={to_output_name(resolve(p.stem,syll)) for p in sources}
    output=ROOT/cfg['paths']['output']
    assert names <= {p.name for p in output.glob('LessonNote_*.pdf')}, 'Run python main.py first'
    mtimes={name:(output/name).stat().st_mtime_ns for name in names}
    result=run();assert result.returncode==0,result.stdout+result.stderr
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    assert len(report['items'])==13
    for item in report['items']:
        assert item['status']=='موفق' and item['qc']['passed'],item
        assert all(item['qc']['checks'].values())
        assert (output/item['output']).stat().st_mtime_ns>mtimes[item['output']]
        assert all(not p['coverage_after_fit'][0]['meaningful_ink_pixels'] and not p['coverage_after_fit'][1]['meaningful_ink_pixels'] for p in item['pages'])
    assert {p.name for p in output.glob('LessonNote_*.pdf')}==names
    assert (output/'report.txt').read_bytes().startswith(b'\xef\xbb\xbf')
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in before.items())
    assert 'LessonNote_hard_ECONO_GO_P_7_v01.pdf' in names


def test_unknown_does_not_stop_next_file_and_ignores_generated(tmp_path):
    directory=ROOT/'tests/data/cli_inputs';directory.mkdir(exist_ok=True)
    make_pdf(directory/'000_unknown_namak.pdf')
    make_pdf(directory/'physics_thermo_8.pdf')
    make_pdf(directory/'LessonNote_ignore.pdf')
    out=tmp_path/'batch'
    result=run('--input',directory,'--output',out)
    assert result.returncode==1
    items=json.loads((out/'report.json').read_text(encoding='utf-8'))['items']
    assert [i['status'] for i in items]==['خطا','موفق']
    assert 'نامک در سیلابس پیدا نشد' in items[0]['error']
    assert len(list(out.glob('*.pdf')))==1


def test_merge_order_one_cover_and_first_orientation(tmp_path):
    a=tmp_path/'a.pdf';b=tmp_path/'b.pdf'
    make_pdf(a,'first',(800,500));make_pdf(b,'second',(600,800))
    out=tmp_path/'merged'
    result=run('--merge',a,b,'--namak','physics_thermo_9','--output',out)
    assert result.returncode==0,result.stdout+result.stderr
    with fitz.open(out/to_output_name('physics_thermo_9')) as doc:
        assert len(doc)==3 and doc[0].rect.width>doc[0].rect.height
        assert 'first' in doc[1].get_text() and 'second' in doc[2].get_text()


def test_missing_libreoffice(tmp_path,monkeypatch):
    word=tmp_path/'physics_thermo_8.docx';word.write_bytes(b'test')
    monkeypatch.setattr(app,'find_soffice',lambda:None)
    out=tmp_path/'office'
    assert app.main(['--input',str(word),'--output',str(out)])==1
    assert 'LibreOffice نصب نیست' in (out/'report.txt').read_text(encoding='utf-8-sig')


def test_rejected_qc_never_replaces_existing_file(tmp_path,monkeypatch):
    source=tmp_path/'physics_thermo_8.pdf';make_pdf(source)
    out=tmp_path/'reject';out.mkdir()
    target=out/to_output_name(source.stem);target.write_bytes(b'old-output')
    monkeypatch.setattr(app,'check_pdf',lambda *a,**k:{'passed':False,'checks':{'injected failure':False},'details':[]})
    assert app.main(['--input',str(source),'--output',str(out)])==1
    assert target.read_bytes()==b'old-output'


def test_full_page_image_has_no_number_warning():
    with fitz.open() as src:
        p=src.new_page(width=600,height=800)
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,20,20),False);pix.clear_with(50)
        p.insert_image(p.rect,pixmap=pix)
        result,report=process_pages(src)
        try:
            assert report['content_uncovered']
            assert not any(w['kind']=='image_number_unknown' for w in report['warnings'])
        finally: result.close()


def test_protected_output_is_rejected():
    with pytest.raises(ValueError,match='مسیر خروجی'):
        app.safe_output(ROOT/'input',load_config())


def test_all_sources_match_recorded_step4_baseline():
    expected=json.loads((ROOT/'tests/data/step4_source_hashes.json').read_text(encoding='utf-8'))
    expected.update(json.loads((ROOT/'tests/data/step4b_source_hashes.json').read_text(encoding='utf-8')))
    actual={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('input','assets','samples') for p in (ROOT/folder).iterdir() if p.is_file()}
    assert actual==expected


def test_image_hashes_include_repeated_uses():
    from qc import image_signature
    with fitz.open() as a,fitz.open() as b:
        p=a.new_page();q=b.new_page()
        pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,10,10),False);pix.clear_with(80)
        p.insert_image(fitz.Rect(10,10,20,20),pixmap=pix)
        q.insert_image(fitz.Rect(10,10,20,20),pixmap=pix)
        assert image_signature(a,p)==image_signature(b,q)
        q.insert_image(fitz.Rect(30,30,40,40),pixmap=pix)
        assert image_signature(a,p)!=image_signature(b,q)


@pytest.mark.skipif(sys.platform!='win32',reason='Windows batch launcher')
def test_windows_batch_launcher(tmp_path):
    source=tmp_path/'physics_thermo_8.pdf';make_pdf(source)
    out=tmp_path/'batch_launcher'
    result=subprocess.run(['cmd','/c',str(ROOT/'run.bat'),'--input',str(source),'--output',str(out)],
                          cwd=ROOT,input='\n',capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120)
    assert result.returncode==0,result.stdout+result.stderr
    assert '1 موفق' in result.stdout
    assert (out/to_output_name(source.stem)).is_file()
