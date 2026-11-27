"""QA syllabus contracts and independently read workbook checks."""
from collections import Counter, defaultdict
from pathlib import Path
import openpyxl
import pytest
from syllabus import Syllabus, load_config, normalize_key, SchemaError, AmbiguousError, NotFoundError

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def real():
    return Syllabus(ROOT/'config.yaml')

@pytest.mark.parametrize('kind',['soal','pasokh'])
def test_real_physics(real,kind):
    row=real.find('physics_electro_1_'+kind)
    assert row['kind']==kind
    assert row['course']=='الکتریسیته'
    assert row['teacher']

@pytest.mark.parametrize('kind',['soal','pasokh'])
def test_real_empty_biology(real,kind):
    with pytest.raises(SchemaError,match='EMPTY_SYLLABUS_RECORD'):
        real.find('ZIST_intro_1.2_'+kind)
    assert real.lookup_warnings==[{'kind':'empty_cover_fields','fields':real.config['qa']['cover']['fields']}]


def test_independent_qa_records_counts_and_pairs(real):
    cfg=real.config;counts=Counter();pairs={};groups=defaultdict(list)
    wb=openpyxl.load_workbook(real.workbook_path,read_only=True,data_only=True)
    try:
        for subject,index in cfg['sheet_to_template'].items():
            pairs[subject]={}
            for kind,spec in cfg['qa']['kinds'].items():
                sheet=subject+spec['sheet_suffix'];ws=wb[sheet]
                rows=list(ws.iter_rows(values_only=True))
                # The QA workbook contract specifies first-row headers.
                header=rows[0]
                columns={field:next(i for i,v in enumerate(header) if v in aliases)
                         for field,aliases in cfg['headers'].items()}
                assert real.column_map[sheet]['header_row']==1
                names=set()
                for values in rows[1:]:
                    raw=values[columns['namak']]
                    if raw is None or not str(raw).strip():continue
                    expected={field:(values[i].strip() if isinstance(values[i],str) else values[i])
                              for field,i in columns.items()}
                    expected.update(sheet=sheet,template_index=index,kind=kind)
                    key=normalize_key(expected['namak'])
                    groups[key].append(expected);counts[kind]+=1
                    suffix='_'+normalize_key(spec['namak_suffix'])
                    assert key.endswith(suffix)
                    names.add(key[:-len(suffix)])
                pairs[subject][kind]=names
    finally:wb.close()
    actual=Counter(row['record']['kind'] for rows in real._index.values() for row in rows if 'kind' in row['record'])
    assert actual==counts
    assert all(len({frozenset(v) for v in kinds.values()})==1 for kinds in pairs.values())
    for key,rows in groups.items():
        if any(row!=rows[0] for row in rows[1:]):
            with pytest.raises(AmbiguousError):real.find(key)
        elif all(rows[0][field] is None or not str(rows[0][field]).strip() for field in cfg['qa']['cover']['fields']):
            with pytest.raises(SchemaError,match='EMPTY_SYLLABUS_RECORD'):real.find(key)
        else:
            assert real.find(key)==rows[0]
    assert real.find('ADAB_NAS_1_soal')['namak']==groups[normalize_key('ADAB_NAS_1_soal')][0]['namak']


def test_real_partial_empty_fields_are_reported(real):
    rows=[r['record'] for group in real._index.values() for r in group
          if r['record'].get('kind') in real.config['qa']['kinds']
          and not r['record']['topic'] and (r['record']['chapter'] or r['record']['course'])]
    assert rows
    record=real.find(rows[0]['namak'])
    assert not record['topic']
    assert any('topic' in warning.get('fields',[]) for warning in real.lookup_warnings)

@pytest.fixture
def make_book(tmp_path):
    def build(qa_rows=None,note_rows=None,video_rows=None,duplicate_header=False):
        cfg=load_config(ROOT/'config.yaml')
        cfg['sheet_to_template']={'Subject':1};cfg['fallback_sheet']='Video'
        cfg['qa']['kinds']={'questions':{'sheet_suffix':'-Q','namak_suffix':'_q'},
                            'answers':{'sheet_suffix':'-A','namak_suffix':'_a'}}
        header=[cfg['headers'][field][0] for field in ('namak','teacher','course','chapter','topic')]
        wb=openpyxl.Workbook();wb.active.title='Subject'
        wb.active.append(header)
        for row in note_rows or [['lesson','teacher','Subject','chapter','topic']]:wb.active.append(row)
        if qa_rows is not None:
            ws=wb.create_sheet('Subject-Q');ws.append(header)
            if duplicate_header:ws.append(header)
            for row in qa_rows:ws.append(row)
        if video_rows is not None:
            ws=wb.create_sheet('Video');ws.append(['intro']);ws.append(header)
            for row in video_rows:ws.append(row)
        path=tmp_path/'book.xlsx';wb.save(path);wb.close()
        return Syllabus.from_workbook(path,cfg)
    return build


def test_missing_qa_is_warning_and_note_unchanged(make_book):
    s=make_book()
    assert s.find('lesson')['kind']=='note'
    assert s.warnings==['MISSING_QA_SHEET: Subject-Q','MISSING_QA_SHEET: Subject-A']
    with pytest.raises(NotFoundError):s.find('lesson_q')


def test_kind_comes_from_sheet_and_teacher_does_not_make_qa_nonempty(make_book):
    s=make_book([['entry_q','teacher',None,None,None]])
    with pytest.raises(SchemaError,match='EMPTY_SYLLABUS_RECORD'):s.find('entry_q')
    assert s.find('lesson')['kind']=='note'


def test_note_teacher_only_is_still_valid(make_book):
    s=make_book(note_rows=[['lesson','teacher',None,None,None]])
    assert s.find('lesson')['kind']=='note'
    assert not s.lookup_warnings

@pytest.mark.parametrize('video',[False,True])
def test_cross_kind_collision_is_ambiguous(make_book,video):
    s=make_book([['collision','t','Subject','c','p']],
                note_rows=None if video else [['collision','t','Subject','c','p']],
                video_rows=[['collision','t','Subject','c','p']] if video else None)
    with pytest.raises(AmbiguousError):s.find('collision')


def test_qa_never_uses_video_fallback(make_book):
    s=make_book(video_rows=[['entry_q','t','Subject','c','p'],['video','t','Subject','c','p']])
    with pytest.raises(NotFoundError):s.find('entry_q')
    assert s.find('video')['kind']=='note'


def test_suffix_is_not_removed_or_added(make_book):
    s=make_book([['qa_only_q','t','Subject','c','p']])
    assert s.find('qa_only_q')['kind']=='questions'
    for key in ('qa_only','lesson_q'):
        with pytest.raises(NotFoundError):s.find(key)


def test_qa_header_must_be_unique(make_book):
    with pytest.raises(SchemaError,match='exactly one namak header'):
        make_book([['entry_q','t','Subject','c','p']],duplicate_header=True)
