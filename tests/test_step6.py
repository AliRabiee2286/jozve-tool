"""Stage 2: video-sheet lookup, empty cover values, and descriptive suffixes."""
from pathlib import Path
import json
import openpyxl
import numpy as np
import pymupdf as fitz
import pytest
import main as app
from syllabus import Syllabus, load_config, AmbiguousError, SchemaError, discover_assets
from naamak import resolve_details, to_output_name
from cover import build_cover, detect_regions, CoverError
from pages import raster, process_pages, _preserve_rendering_attributes
from qc import check_pdf


ROOT=Path(__file__).resolve().parents[1]
FIELDS=['teacher','course','chapter','topic']
HEAD=['نامک','نام استاد','درس','فصل','مبحث']
pytestmark=pytest.mark.slow


def make_book(tmp_path, primary=(), fallback=()):
    tmp_path.mkdir(parents=True,exist_ok=True)
    cfg=load_config()
    cfg['sheet_to_template']={'شیمی':14,'سلول':10,'سواد رسانه':7}
    book=openpyxl.Workbook();book.remove(book.active)
    for name in cfg['sheet_to_template']:
        sheet=book.create_sheet(name)
        sheet.append(HEAD)
        if name=='شیمی':
            for row in primary:
                sheet.append(row)
    video=book.create_sheet(cfg['fallback_sheet'])
    video.append(['مقدمه'])
    video.append(HEAD)
    for row in fallback:
        video.append(row)
    path=tmp_path/'source.xlsx'
    book.save(path);book.close()
    return Syllabus.from_workbook(path,cfg)


def test_video_alias_and_subject_priority(tmp_path):
    syllabus=make_book(tmp_path,
        [['both','اول','شیمی','فصل','مبحث']],
        [['both','دوم','سلول',None,None],['video','معلم','سواد',None,None]])
    assert syllabus.find('both')['teacher']=='اول'
    assert syllabus.lookup_warnings[0]['kind']=='syllabus_source_conflict'
    row=syllabus.find('video')
    assert row['sheet']=='سواد رسانه' and row['template_index']==7 and row['course']=='سواد'
    assert syllabus.lookup_warnings==[]
    assert syllabus.column_map[syllabus.config['fallback_sheet']]['header_row']==2


@pytest.mark.parametrize('different',[False,True])
def test_video_duplicate_rows(tmp_path,different):
    row=['video','معلم','سلول',None,None]
    second=list(row)
    if different:
        second[1]='دیگری'
    syllabus=make_book(tmp_path,fallback=[row,second])
    if different:
        with pytest.raises(AmbiguousError):
            syllabus.find('video')
    else:
        assert syllabus.find('video')['template_index']==10


def test_unknown_video_subject_has_coded_error(tmp_path):
    syllabus=make_book(tmp_path,fallback=[['video','معلم','ناشناخته',None,None]])
    with pytest.raises(SchemaError,match='UNKNOWN_VIDEO_FIELD'):
        syllabus.find('video')


def test_unsolved_match_first_and_output_name(tmp_path):
    syllabus=make_book(tmp_path,fallback=[['Dore 22','معلم','شیمی',None,None]])
    for name in ['Dore_22_unsolved.pdf','Dore 22 unsolved (1).pdf']:
        assert resolve_details(name,syllabus)=={'namak':'Dore 22','suffix':'unsolved'}
    assert to_output_name('Dore 22',suffix='unsolved')=='LessonNote_hard_Dore_22_unsolved_v01.pdf'
    with pytest.raises(ValueError,match='UNSUPPORTED_OUTPUT_SUFFIX'):
        to_output_name('x',suffix='unapproved')

    primary=make_book(tmp_path/'primary',
        [['Dore_22_unsolved','اصل','سلول',None,None]])
    assert resolve_details('Dore_22_unsolved.pdf',primary)=={
        'namak':'Dore_22_unsolved','suffix':''}


@pytest.fixture(scope='module')
def filled_references():
    result={}
    for orientation in ('portrait','landscape'):
        document,_=build_cover(10,orientation,dict.fromkeys(FIELDS,'متن'))
        with document:
            result[orientation]=raster(document[0],150)
    return result


@pytest.mark.parametrize('orientation',['portrait','landscape'])
@pytest.mark.parametrize('mask',range(1,16))
def test_each_nonempty_combination_preserves_blank_regions(mask,orientation,filled_references):
    cfg=load_config()
    values={field:('متن' if mask & (1<<index) else [None,'','  ','\t'][index])
            for index,field in enumerate(FIELDS)}
    document,report=build_cover(10,orientation,values)
    with document,fitz.open(discover_assets(cfg,ROOT)['template']) as templates:
        blank=templates[report['template_page']-1]
        regions,_,_=detect_regions(blank,cfg['cover'])
        generated=raster(document[0],150)
        reference=raster(blank,150)
        changed=np.any(generated!=reference,axis=2)
        allowed=np.zeros(changed.shape,dtype=bool)
        for index,field in enumerate(FIELDS):
            x0,y0,x1,y1=(regions[field]*(150/72)).irect
            allowed[y0:y1,x0:x1]=True
            present=bool(mask & (1<<index))
            assert bool(changed[y0:y1,x0:x1].any())==present
            assert report['fields'][field]['value']==values[field]
            assert report['fields'][field].get('empty',False)==(not present)
            if present:
                assert np.array_equal(generated[y0:y1,x0:x1],
                                      filled_references[orientation][y0:y1,x0:x1])
        assert not changed[~allowed].any()


def test_all_empty_and_nontext_values_are_rejected():
    with pytest.raises(CoverError,match='EMPTY_SYLLABUS_RECORD'):
        build_cover(10,'portrait',dict(zip(FIELDS,[None,'',' ','\t'])))
    with pytest.raises(CoverError,match='INVALID_SYLLABUS_VALUE'):
        build_cover(10,'portrait',dict(zip(FIELDS,[3,'متن',None,None])))


def test_visible_damage_in_filled_cover_field_is_blocking(tmp_path):
    record={'namak':'synthetic','sheet':'سلول','template_index':10,
            'teacher':'استاد','course':'سلول','chapter':None,'topic':None}
    with fitz.open() as source:
        source.new_page(width=595,height=842)
        cover,cover_report=build_cover(10,'portrait',
                                       {field:record[field] for field in FIELDS})
        content,page_report=process_pages(source)
        with cover,content,fitz.open(stream=cover.tobytes(),filetype='pdf') as result:
            result.insert_pdf(content)
            _preserve_rendering_attributes(content,result,1,preserve_catalog=False)
            good=tmp_path/'good.pdf';result.save(good)
            quality=check_pdf(good,source,record,cover_report,page_report,cover,
                              output_name=to_output_name(record['namak']))
            assert quality['passed']
            box=fitz.Rect(cover_report['fields']['teacher']['bbox'])
            result[0].draw_rect(fitz.Rect(box.x0+10,box.y0+5,box.x0+30,box.y0+15),
                                fill=(0,0,0),color=None)
            bad=tmp_path/'bad.pdf';result.save(bad)
            quality=check_pdf(bad,source,record,cover_report,page_report,cover,
                              output_name=to_output_name(record['namak']))
            assert not quality['passed']
            assert not quality['checks']['فرست‌پیج بدون بوردر و برابر مرجع نوشتن']


@pytest.mark.parametrize('all_empty',[False,True])
def test_empty_values_are_reported(tmp_path,monkeypatch,capsys,all_empty):
    cfg=load_config();cfg['sheet_to_template']={'شیمی':14}
    book=openpyxl.Workbook();sheet=book.active;sheet.title='شیمی'
    sheet.append(HEAD)
    sheet.append(['example',None if all_empty else 'استاد',
                  None if all_empty else 'شیمی',None,' '])
    workbook=tmp_path/'book.xlsx';book.save(workbook);book.close()
    syllabus=Syllabus.from_workbook(workbook,cfg)
    monkeypatch.setattr(app,'Syllabus',lambda:syllabus)
    source=tmp_path/'example.pdf'
    with fitz.open() as document:
        document.new_page(width=595,height=842);document.save(source)
    output=tmp_path/'result'
    code=app.main(['--input',str(source),'--output',str(output)])
    assert code==int(all_empty)
    terminal=capsys.readouterr().out
    assert 'empty syllabus values:' in terminal
    assert 'empty syllabus values:' in (output/'log.txt').read_text(encoding='utf-8')
    report=(output/'report.txt').read_text(encoding='utf-8-sig')
    assert 'مقدار خالی در سیلابس:' in report
    if all_empty:
        assert 'EMPTY_SYLLABUS_RECORD' in report
        assert not list(output.glob('*.pdf'))
    else:
        assert 'فصل، مبحث' in report
        assert json.loads((output/'report.json').read_text(encoding='utf-8'))['items'][0]['qc']['passed']
