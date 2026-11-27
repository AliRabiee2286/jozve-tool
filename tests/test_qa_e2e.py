"""Q8 end-to-end acceptance; fixed QA hashes and genuine CLI isolation."""
from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
from pathlib import Path
import hashlib,json,shutil
import pymupdf as fitz
import pytest
import main
from syllabus import Syllabus

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.slow
NOTES=['ai_par_2.pdf','nojoom_astr_18.pdf']

class TTY(StringIO):
    def isatty(self):return True


def hashes(path):
    with fitz.open(path) as doc:
        result=[]
        for i,page in enumerate(doc,1):
            pix=page.get_pixmap(dpi=72,alpha=False)
            result.append({'page':i,'width':pix.width,'height':pix.height,'sha256':hashlib.sha256(pix.samples).hexdigest()})
        return result


def invoke(args,monkeypatch,mode='plain'):
    stream=TTY();opened=[];selected=[];real_ui=main.TerminalUI
    def ui(*a,**kw):
        result=real_ui(*a,**kw);selected.append((result.mode,result.quiet));return result
    with monkeypatch.context() as patch:
        patch.setenv('WT_SESSION','q8-test')
        patch.delenv('NO_COLOR',raising=False)
        patch.setattr(main,'TerminalUI',ui)
        patch.setattr(main.webbrowser,'open',lambda uri:opened.append(uri) or True)
        options=['--ui','plain','--quiet'] if mode=='quiet' else ['--ui',mode,'--verbose']
        with redirect_stdout(stream),redirect_stderr(stream):
            code=main.main([*args,*options,'--no-thumbs','--open-report'])
    return code,stream.getvalue(),opened,selected


def report(output):return json.loads((output/'report.json').read_text(encoding='utf-8'))


def test_fixed_baseline_and_repeat(monkeypatch):
    output=ROOT/'tests/results/qa';baseline=json.loads((ROOT/'tests/qa_baseline.json').read_text(encoding='utf-8'))
    previous=None
    for _ in range(2):
        code,text,opened,_=invoke(['--input',str(ROOT/'tests/data/qa'),'--output',str(output)],monkeypatch)
        assert code==0,text
        data=report(output);assert data['counts']=={'OK':1,'REVIEW':1,'BLOCKED':0}
        current={}
        for item in data['items']:
            path=output/item['output'];assert item['qc']['passed']
            assert hashes(path)==baseline['files'][path.name]['pages']
            assert len(hashes(path))==2
            current[path.name]=path.stat().st_mtime_ns
        if previous:assert all(current[k]>previous[k] for k in current)
        previous=current
        assert opened==[(output/'report.html').resolve().as_uri()]


@pytest.fixture(scope='module')
def mixed():
    directory=ROOT/'tests/data/mixed/q8';directory.mkdir(parents=True,exist_ok=True)
    for name in NOTES:shutil.copy2(ROOT/'input'/name,directory/name)
    for path in (ROOT/'tests/data/qa').glob('*.pdf'):shutil.copy2(path,directory/path.name)
    return directory,{}


@pytest.mark.parametrize('mode',['fancy','compat','plain','quiet'])
def test_mixed_ui_and_open_report(mixed,monkeypatch,mode):
    directory,reference=mixed;output=ROOT/'tests/results'/('q8_ui_'+mode)
    code,text,opened,selected=invoke(['--input',str(directory),'--output',str(output)],monkeypatch,mode)
    assert code==0,text
    assert selected==[('plain' if mode=='quiet' else mode,mode=='quiet')]
    assert opened==[(output/'report.html').resolve().as_uri()]
    data=report(output);assert data['counts']=={'OK':3,'REVIEW':1,'BLOCKED':0}
    assert len(data['items'])==4 and all(i['qc']['passed'] for i in data['items'])
    for item in data['items']:
        current=hashes(output/item['output'])
        if item['output'] not in reference:reference[item['output']]=current
        assert current==reference[item['output']]
    (output/'console_capture.txt').write_text(text,encoding='utf-8')
    (output/'ui_probe.json').write_text(json.dumps({'selected':selected,'open_report_uri':opened,'browser_stubbed':True}),encoding='utf-8')


@pytest.mark.parametrize('problem',['landscape','encrypted','formula','corrupt'])
def test_bad_qa_does_not_stop_note(tmp_path,monkeypatch,problem):
    directory=tmp_path/'input';directory.mkdir();output=tmp_path/'output'
    shutil.copy2(ROOT/'input'/NOTES[0],directory/NOTES[0])
    bad=directory/'2026-11-14_shimi_physic_20_soal.pdf'
    with fitz.open() as doc:
        doc.new_page(width=842 if problem=='landscape' else 595,height=595 if problem=='landscape' else 842)
        options={'encryption':fitz.PDF_ENCRYPT_AES_256,'owner_pw':'test-owner','user_pw':'test-user'} if problem=='encrypted' else {}
        doc.save(bad,**options)
    if problem=='corrupt':bad.write_bytes(b'broken QA PDF')
    if problem=='formula':
        original=Syllabus.find
        def find(self,*a,**kw):
            record=original(self,*a,**kw)
            return dict(record,topic='√') if record.get('kind')=='soal' else record
        monkeypatch.setattr(Syllabus,'find',find)
    code,text,opened,_=invoke(['--input',str(directory),'--output',str(output)],monkeypatch)
    assert code==1,text
    data=report(output);assert data['counts']=={'OK':1,'REVIEW':0,'BLOCKED':1}
    assert [i['status_code'] for i in data['items']]==['BLOCKED','OK']
    blocked=next(i for i in data['items'] if i['status_code']=='BLOCKED')
    assert blocked['kind']=='soal'
    if problem=='formula':assert 'FORMULA_GLYPH_MISSING' in blocked['error']
    note=next(i for i in data['items'] if i['status_code']=='OK')
    assert note.get('kind','note')=='note' and note['qc']['passed']
    assert not (output/blocked['output']).exists()
    assert 'سوالات' in (output/'report.html').read_text(encoding='utf-8')
    assert 'نوع: سوالات' in (output/'report.txt').read_text(encoding='utf-8-sig')
    proof=ROOT/'debug/qa_e2e'/problem;proof.mkdir(exist_ok=True)
    for name in ('report.json','report.txt','report.html'):
        shutil.copy2(output/name,proof/name)


@pytest.mark.parametrize('namak,subject',[
    ('Dore 22','شیمی'),('dore 23','شیمی'),('dore 24','شیمی'),
    ('SCELL_AD_2_3','سلول'),('SCELL_AD_2_4','سلول'),
    ('SCELL_BQ_1','سلول'),('SCELL_BQ_2','سلول'),('SCELL_BQ_3','سلول')])
def test_approved_video_alias_preserves_values(namak,subject):
    from syllabus import normalize_key
    syllabus=Syllabus();record=syllabus.find(namak)
    raw=syllabus._fallback_index[normalize_key(namak)][0]['record']
    assert record['sheet']==subject and record['kind']=='note'
    assert all(record[key]==raw[key] for key in ('teacher','course','chapter','topic'))
