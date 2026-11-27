"""Q7b presentation, event contracts and mixed-mode integration."""
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import pymupdf as fitz
import pytest
import main
import qa_pipeline
from events import EventBus
from syllabus import Syllabus, load_config
from ui import TerminalUI
from qa_labels import qa_subject_label
from report_html import _subject_icon

ROOT=Path(__file__).resolve().parents[1]
STAGES=['resolve','cover','pages','qc','write']

class TTY(StringIO):
    def isatty(self):return True

@pytest.fixture(scope='module')
def syllabus():return Syllabus()


def make_pdf(path):
    with fitz.open() as doc:
        page=doc.new_page();page.insert_text((100,150),'Preserved content')
        doc.save(path)


@pytest.mark.parametrize('mode',['fancy','compat','plain'])
@pytest.mark.parametrize('kind',['soal','pasokh'])
def test_labels_all_ui_modes(mode,kind):
    cfg=load_config();spec=cfg['qa']['kinds'][kind]
    sheet='فیزیک'+spec['sheet_suffix']
    stream=TTY();ui=TerminalUI(mode,stream=stream,environ={'WT_SESSION':'1'},config=cfg,verbose=True)
    expected='physics ('+spec['title_en']+')'
    assert ui._subject_label({'sheet':sheet},6)==expected
    assert ui._subject_label({'sheet':'فیزیک'},6)=='physics'
    ui.handle_event('file_started',{'file':'qa.pdf','index':1,'total':1})
    for stage in STAGES:
        ui.handle_event('stage_started',{'file':'qa.pdf','stage':stage})
        ui.handle_event('stage_finished',{'file':'qa.pdf','stage':stage,'ok':True,'seconds':0.01})
    ui.handle_event('file_done',{'file':'qa.pdf','item':{'sheet':sheet,'status_code':'OK'},'seconds':1})
    if mode=='fancy':
        from rich.console import Console
        ui._console=Console(file=stream,width=200,height=35,force_terminal=True)
        ui._console.print(ui.render())
        assert expected in stream.getvalue()
    else:
        for stage in ('Resolve','Cover','Pages','QC','Write'):
            assert 'Stage '+stage+': started' in stream.getvalue()
    assert 'field #' not in stream.getvalue()


def test_labels_and_icons_are_config_driven():
    cfg=deepcopy(load_config());cfg['field_labels_en']['فیزیک']='custom physics'
    cfg['qa']['kinds']['soal'].update(sheet_suffix='::questions',title_en='questions')
    assert qa_subject_label('فیزیک::questions',cfg)=='custom physics (questions)'
    assert _subject_icon({'sheet':'فیزیک::questions'},cfg)==_subject_icon({'sheet':'فیزیک'},cfg)
    assert qa_subject_label('unknown',cfg) is None


@pytest.mark.parametrize('kind',['soal','pasokh'])
def test_all_base_subject_icons(kind):
    cfg=load_config()
    for base in cfg['field_labels_en']:
        qa=base+cfg['qa']['kinds'][kind]['sheet_suffix']
        assert _subject_icon({'sheet':qa},cfg)==_subject_icon({'sheet':base},cfg)
        assert qa_subject_label(qa,cfg).startswith(cfg['field_labels_en'][base]+' (')


def test_dry_run_qa_labels(tmp_path,capsys):
    for name in ('physics_electro_1_soal','shimi_physic_20_pasokh','physics_thermo_8'):
        make_pdf(tmp_path/(name+'.pdf'))
    assert main.main(['--dry-run','--input',str(tmp_path)])==0
    text=capsys.readouterr().out
    assert 'physics (soal)' in text and 'chemistry (pasokh)' in text
    assert 'field #' not in text and 'physics | note' in text


def capture():
    bus=EventBus();events=[]
    for name in ('stage_started','stage_finished','stage_progress'):
        bus.subscribe(name,lambda payload,name=name:events.append((name,payload)))
    return bus,events


def test_stage_events_and_empty_warning(tmp_path,syllabus,monkeypatch):
    record=dict(syllabus.find('shimi_physic_20_soal'),topic=None)
    monkeypatch.setattr(syllabus,'find',lambda *a,**kw:record)
    path=tmp_path/'shimi_physic_20_soal.pdf';make_pdf(path)
    bus,events=capture()
    item=main.process_job([path],None,syllabus,load_config(),tmp_path,set(),bus)
    assert item['status_code']=='OK',item
    assert {'kind':'empty_cover_fields','fields':['topic']} in item['warnings']
    assert [p['stage'] for n,p in events if n=='stage_started']==STAGES
    assert [p['stage'] for n,p in events if n=='stage_finished']==STAGES
    assert all(p['ok'] and p['seconds']>=0 for n,p in events if n=='stage_finished')
    assert all(p['file']==path.name for n,p in events)
    assert any(n=='stage_progress' and p['index']==p['total']==1 for n,p in events)


@pytest.mark.parametrize('failed',['cover','pages','qc','write'])
def test_failed_stages_finish_and_stop(tmp_path,syllabus,monkeypatch,failed):
    path=tmp_path/'shimi_physic_20_soal.pdf';make_pdf(path)
    def fail(*a,**kw):raise RuntimeError('intentional stage failure')
    if failed in ('cover','pages'):
        monkeypatch.setattr(qa_pipeline,'build_qa_cover' if failed=='cover' else 'process_qa_pages',fail)
    elif failed=='qc':
        import qa_qc
        monkeypatch.setattr(qa_qc,'check_qa_pdf',lambda *a,**kw:{'passed':False,'blocking_failed':['test'],'advisory_failed':[]})
    else:monkeypatch.setattr(qa_pipeline.os,'replace',fail)
    bus,events=capture()
    item=main.process_job([path],None,syllabus,load_config(),tmp_path,set(),bus)
    assert item['status_code']=='BLOCKED'
    finished=[p for n,p in events if n=='stage_finished']
    assert [p['stage'] for p in finished]==STAGES[:STAGES.index(failed)+1]
    assert not finished[-1]['ok'] and 'error' in finished[-1]
    assert all(p['ok'] for p in finished[:-1])


@pytest.mark.slow
def test_mixed_cli_notes_questions_answers(tmp_path,capsys):
    source=tmp_path/'input';source.mkdir();output=tmp_path/'output'
    for name in ('physics_thermo_8','shimi_physic_20_soul','shimi_physic_20_pasokh'):
        make_pdf(source/(name+'.pdf'))
    assert main.main(['--input',str(source),'--output',str(output),'--ui','plain','--verbose','--no-thumbs'])==0
    items=json.loads((output/'report.json').read_text(encoding='utf-8'))['items']
    assert len(items)==3
    assert {i.get('kind','note'):i['status_code'] for i in items}=={'note':'OK','soal':'REVIEW','pasokh':'OK'}
    assert all(i['qc']['passed'] for i in items)
    note=next(i for i in items if i.get('kind','note')=='note')
    assert set(note['cover']['fields'])=={'teacher','course','chapter','topic'}
    for item in items:
        if item is not note:assert set(item['cover']['fields'])=={'course','chapter','topic'}
        with fitz.open(output/item['output']) as doc:assert len(doc)==2
    stdout=capsys.readouterr().out
    for stage in ('Resolve','Cover','Pages','QC','Write'):
        assert stdout.count('Stage '+stage+': started')==3
    html=(output/'report.html').read_text(encoding='utf-8')
    assert 'سوالات' in html and 'پاسخنامه' in html

    # Retain reviewable evidence from the successful mixed integration test.
    import shutil
    proof=ROOT/'debug/qa_alignment';proof.mkdir(exist_ok=True)
    for name in ('report.html','report.json','report.txt','log.jsonl'):
        if (output/name).exists():shutil.copy2(output/name,proof/name)
    (proof/'console.txt').write_text(stdout,encoding='utf-8')
    for item in items:
        shutil.copy2(output/item['output'],proof/item['output'])
        with fitz.open(output/item['output']) as doc:
            doc[0].get_pixmap(dpi=100).save(proof/(item.get('kind','note')+'_cover.png'))


def test_every_real_qa_sheet_has_label(syllabus):
    cfg=load_config()
    sheets={v['record']['sheet'] for group in syllabus._index.values() for v in group
            if v['record'].get('kind') in cfg['qa']['kinds']}
    assert len(sheets)==28
    assert all(qa_subject_label(sheet,cfg) for sheet in sheets)
