"""Q7: independently damaged PDFs must never be published as successful."""
from copy import deepcopy
from pathlib import Path
import pymupdf as fitz
import pytest
from syllabus import Syllabus, load_config
from naamak import to_output_name
from qa_pipeline import assemble_qa
from qa_qc import check_qa_pdf
from main import process_job

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def sample():
    syllabus=Syllabus()
    record=syllabus.find('shimi_physic_20_soal')
    source=fitz.open();page=source.new_page()
    page.insert_text((100,150),'Preserved body content')
    pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,8,8));pix.clear_with(128)
    page.insert_image(fitz.Rect(100,200,160,260),pixmap=pix)
    page.insert_text((290,825),'1')
    document,cover,pages=assemble_qa(source,record)
    data=document.tobytes();document.close()
    yield source,record,cover,pages,data,syllabus
    source.close()


def run(sample,tmp_path,mutate=None,report_change=None,name=None):
    source,record,cover,pages,data,_=sample
    cover,pages=deepcopy(cover),deepcopy(pages)
    path=tmp_path/(name or to_output_name(record['namak']))
    with fitz.open(stream=data,filetype='pdf') as doc:
        if mutate:mutate(doc)
        doc.save(path)
    if report_change:report_change(cover,pages)
    return check_qa_pdf(path,source,record,cover,pages)


def rejected(result,check):
    assert not result['passed'],result
    assert any(k.split(': ',1)[-1]==check and not v for k,v in result['checks'].items()),result


def test_valid(sample,tmp_path):
    result=run(sample,tmp_path)
    assert result['passed'],result
    assert all(result['checks'].values())


@pytest.mark.parametrize('case,check',[
    ('count','تعداد صفحات'),('name','نام فایل'),('evidence','تعداد شواهد صفحات'),
    ('cover_geometry','اندازه و جهت فرست‌پیج'),('field','سه مقدار دقیق'),
    ('teacher','نبود استاد و متن اضافی'),('outside','تغییر فقط در سه ناحیه'),
    ('cover_pixels','فرست‌پیج برابر مرجع'),('geometry','اندازه و جهت و rotation'),
    ('body_pixels','رندر محتوا'),('number','نبود شماره متن'),('text','متن حفظ‌شده'),
    ('image','تصاویر حفظ‌شده'),('frame','قاب معتبر'),
    ('structure','ساختار لایه قاب'),('under_frame','جوهر زیر قاب صفر'),
])
def test_negative_pdf(sample,tmp_path,case,check):
    def change(doc):
        page=doc[-1]
        if case=='count':doc.delete_page(-1)
        elif case=='cover_geometry':doc[0].set_rotation(180)
        elif case=='teacher':doc[0].insert_text((100,100),'Unwanted teacher')
        elif case in ('outside','cover_pixels'):doc[0].draw_rect(fitz.Rect(100,100,110,110),fill=(0,0,0))
        elif case=='geometry':page.set_rotation(180)
        elif case=='body_pixels':page.draw_rect(fitz.Rect(200,200,210,210),fill=(0,0,0))
        elif case=='number':page.insert_text((290,825),'7')
        elif case=='text':page.insert_text((200,300),'Injected text')
        elif case=='image':
            pix=fitz.Pixmap(fitz.csRGB,fitz.IRect(0,0,9,9));pix.clear_with(64)
            page.insert_image(fitz.Rect(200,300,230,330),pixmap=pix)
        elif case=='frame':doc.update_stream(page.get_contents()[-1],b'')
        elif case=='under_frame':
            original=page.get_contents()
            page.draw_rect(fitz.Rect(0,100,20,120),fill=(0,0,0))
            added=page.get_contents()[-1]
            order=original[:-8]+[added]+original[-8:]
            doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{x} 0 R' for x in order)+']')
    def metadata(cover,pages):
        if case=='evidence':pages['pages']=[]
        elif case=='field':cover['fields']['course']['value']='Wrong'
        elif case=='structure':pages['pages'][0]['frame_stream_count']=0
        elif case=='under_frame':pages['pages'][0]['content_stream_count']+=1
    result=run(sample,tmp_path,change,metadata,'wrong.pdf' if case=='name' else None)
    rejected(result,check)


def test_corrupt(sample,tmp_path):
    source,record,cover,pages,_,_=sample
    path=tmp_path/to_output_name(record['namak']);path.write_bytes(b'not a PDF')
    rejected(check_qa_pdf(path,source,record,cover,pages),'خطای کنترل کیفیت')


def test_encrypted_qc(sample,tmp_path):
    source,record,cover,pages,data,_=sample
    path=tmp_path/to_output_name(record['namak'])
    with fitz.open(stream=data,filetype='pdf') as doc:
        doc.save(path,encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='test-owner',user_pw='test-user')
    rejected(check_qa_pdf(path,source,record,cover,pages),'باز شدن PDF')


def test_font_missing(sample,tmp_path):
    # A valid font with an extra trailing byte still renders, but is not the required asset.
    from syllabus import discover_assets
    expected=discover_assets(load_config(),ROOT,roles=['font'])['font'].read_bytes()
    def change(doc):
        found=0
        for xref in range(1,doc.xref_length()):
            if doc.xref_is_stream(xref) and doc.xref_stream(xref)==expected:
                doc.update_stream(xref,expected+b'\0');found+=1
        assert found
    rejected(run(sample,tmp_path,change),'فونت Aria جاسازی‌شده')


@pytest.mark.parametrize('kind,alias',[('soal',True),('pasokh',False)])
def test_dispatch_merge_and_review(sample,tmp_path,kind,alias):
    source,_,_,_,_,syllabus=sample
    path=tmp_path/('shimi_physic_20_'+('soul' if alias else kind)+'.pdf')
    source.save(path)
    item=process_job([path,path],None,syllabus,load_config(),tmp_path,set())
    assert item['status_code']==('REVIEW' if alias else 'OK'),item
    assert item['kind']==kind and item['qc']['passed']
    assert set(item['cover']['fields'])=={'course','chapter','topic'}
    with fitz.open(tmp_path/item['output']) as doc:assert len(doc)==3


@pytest.mark.parametrize('case,expected',[
    ('landscape','LANDSCAPE'),('formula','FORMULA_GLYPH_MISSING'),
    ('empty','EMPTY_SYLLABUS_RECORD'),('encrypted','رمزدار'),('corrupt','Failed'),
])
def test_pipeline_blocked(sample,tmp_path,monkeypatch,case,expected):
    _,record,_,_,_,syllabus=sample
    record=deepcopy(record)
    if case=='formula':record['topic']='√'
    if case=='empty':record.update(course='',chapter='',topic='')
    monkeypatch.setattr(syllabus,'find',lambda *a,**kw:record)
    path=tmp_path/'shimi_physic_20_soal.pdf'
    with fitz.open() as doc:
        doc.new_page(width=842 if case=='landscape' else 595,height=595 if case=='landscape' else 842)
        options={'encryption':fitz.PDF_ENCRYPT_AES_256,'owner_pw':'test-owner','user_pw':'test-user'} if case=='encrypted' else {}
        doc.save(path,**options)
    if case=='corrupt':path.write_bytes(b'bad PDF')
    item=process_job([path],None,syllabus,load_config(),tmp_path,set())
    assert item['status_code']=='BLOCKED',item
    assert expected.lower() in item['error'].lower(),item
    assert not (tmp_path/to_output_name(record['namak'])).exists()


def test_reports_have_kind_and_three_fields(sample,tmp_path):
    import json
    from report_text import write_report
    from report_html import write_html_report
    _,record,cover,pages,_,_=sample
    item={'files':['qa.pdf'],'kind':'soal','namak':record['namak'],'status':'موفق',
          'status_code':'OK','cover':cover,'pages':pages['pages'],'warnings':[]}
    write_report(tmp_path,[item],[])
    text=(tmp_path/'report.txt').read_text(encoding='utf-8')
    html=write_html_report(tmp_path,[item],[],thumbs='none').read_text(encoding='utf-8')
    title=load_config()['qa']['kinds']['soal']['title']
    assert 'نوع: '+title in text and title in html
    for field in ('course','chapter','topic'):
        assert str(record[field]) in text and str(record[field]) in html
    assert 'نام استاد' not in text
    assert all('<dt>'+label+'</dt>' not in html for label in load_config()['headers']['teacher'])
    assert json.loads((tmp_path/'report.json').read_text(encoding='utf-8'))['items'][0]['kind']=='soal'


def test_doctor_qa_is_optional(tmp_path):
    import shutil
    from doctor import collect_checks
    shutil.copy(ROOT/'config.yaml',tmp_path/'config.yaml')
    checks=collect_checks(tmp_path)
    qa=[c for c in checks if c['name'] in ('asset template_qa','asset frame_qa','QA assets')]
    assert len(qa)==3
    assert all(not c['ok'] and not c['required'] for c in qa)


def test_doctor_validates_real_qa_assets():
    from doctor import collect_checks
    checks=collect_checks(ROOT)
    assert next(c for c in checks if c['name']=='QA assets')['ok']


def test_rejected_qa_does_not_replace_existing(sample,tmp_path,monkeypatch):
    import qa_qc
    source,record,_,_,_,syllabus=sample
    path=tmp_path/'shimi_physic_20_soal.pdf';source.save(path)
    target=tmp_path/to_output_name(record['namak']);target.write_bytes(b'existing result')
    monkeypatch.setattr(qa_qc,'check_qa_pdf',lambda *a,**k: {'passed':False,'blocking_failed':['test rejection'],'advisory_failed':[]})
    item=process_job([path],None,syllabus,load_config(),tmp_path,set())
    assert item['status_code']=='BLOCKED' and target.read_bytes()==b'existing result'


def test_rotated_and_landscape_content_and_annotations(sample,tmp_path):
    _,record,_,_,_,_=sample
    with fitz.open() as source:
        source.new_page()
        page=source.new_page(width=842,height=595)
        page.insert_text((100,150),'Landscape body')
        page.add_freetext_annot(fitz.Rect(100,200,200,240),'Preserved annotation')
        page=source.new_page();page.insert_text((100,150),'Rotated body');page.set_rotation(90)
        doc,cover,pages=assemble_qa(source,record)
        path=tmp_path/to_output_name(record['namak']);doc.save(path);doc.close()
        result=check_qa_pdf(path,source,record,cover,pages)
        assert result['passed'],result


@pytest.mark.parametrize('missing',[False,True])
def test_office_uses_existing_converter(sample,tmp_path,monkeypatch,missing):
    import main
    source,record,_,_,_,syllabus=sample
    path=tmp_path/'shimi_physic_20_soal.docx';path.write_bytes(b'test converter input')
    called=[]
    def converter(original,directory):
        called.append(original)
        if missing:raise RuntimeError('LibreOffice unavailable')
        directory.mkdir(parents=True);pdf=directory/'converted.pdf';source.save(pdf);return pdf
    monkeypatch.setattr(main,'convert_office',converter)
    item=process_job([path],None,syllabus,load_config(),tmp_path,set())
    assert called==[path]
    assert item['status_code']==('BLOCKED' if missing else 'OK'),item


def test_output_collision_is_blocked(sample,tmp_path):
    source,record,_,_,_,syllabus=sample
    path=tmp_path/'shimi_physic_20_soal.pdf';source.save(path)
    item=process_job([path],None,syllabus,load_config(),tmp_path,{to_output_name(record['namak']).casefold()})
    assert item['status_code']=='BLOCKED'
    assert not (tmp_path/to_output_name(record['namak'])).exists()


def test_qc_accepts_syllabus_empty_field(sample,tmp_path):
    source,record,_,_,_,_=sample
    record=dict(record,topic=None)
    doc,cover,pages=assemble_qa(source,record)
    path=tmp_path/to_output_name(record['namak']);doc.save(path);doc.close()
    result=check_qa_pdf(path,source,record,cover,pages)
    assert result['passed'],result
