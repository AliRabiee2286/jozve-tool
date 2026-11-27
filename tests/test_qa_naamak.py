"""Q3 match-first, approved suffix aliases and canonical output contracts."""
import copy
from pathlib import Path
import pytest
import main as app
from naamak import resolve_details, to_output_name
from syllabus import Syllabus, load_config, normalize_key, NotFoundError, AmbiguousError, SchemaError

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def real():
    return Syllabus(ROOT/'config.yaml')

@pytest.mark.parametrize('source,canonical,kind',[
    ('shimi_physic_20_soul','shimi_physic_20_soal','soal'),
    ('shimi_physic_20_soul (1).pdf','shimi_physic_20_soal','soal'),
    ('shimi_physic_20_soul_1_.pdf','shimi_physic_20_soal','soal'),
    ('2026-11-13_shimi_physic_20_soul.pdf','shimi_physic_20_soal','soal'),
    ('shimi_physic_20_pasokh','shimi_physic_20_pasokh','pasokh'),
    ('shimi_physic_20','shimi_physic_20','note'),
    ('physics_electro_1_soal (1)','physics_electro_1_soal','soal'),
    ('physics_electro_۱_so\u200cal','physics_electro_1_soal','soal'),
])
def test_real_names_and_outputs(real,source,canonical,kind):
    result=resolve_details(source,real)
    assert result['namak']==canonical and result['suffix']==''
    assert real.find(canonical)['kind']==kind
    assert to_output_name(result['namak'])=='LessonNote_hard_'+canonical+'_v01.pdf'
    if 'soul' in source:
        assert result['alias_applied'] is True
        assert result['warnings'][0]['status_code']=='REVIEW'
        assert result['warnings'][0]['target']==canonical
    else:
        assert result=={'namak':canonical,'suffix':''}


def test_missing_alias_target_is_not_found(real):
    with pytest.raises(NotFoundError):resolve_details('absent_987654_soul',real)


class FakeSyllabus:
    def __init__(self,records,aliases=None):
        self.config=copy.deepcopy(load_config(ROOT/'config.yaml'))
        if aliases is not None:self.config['qa']['kind_suffix_aliases']=aliases
        self.records={normalize_key(k):v for k,v in records.items()}
        self.calls=[]
    def find(self,name):
        self.calls.append(name)
        value=self.records.get(normalize_key(name))
        if isinstance(value,Exception):raise value
        if value is None:raise NotFoundError(name)
        return dict(value)


def record(name,kind='soal'):
    return {'namak':name,'kind':kind}


def test_exact_name_precedes_even_ambiguous_alias_table():
    s=FakeSyllabus({'x_soul':record('x_soul','note'),'x_soal':record('x_soal')},
                   {'soul':['soal','pasokh']})
    assert resolve_details('x_soul',s)=={'namak':'x_soul','suffix':''}
    assert s.calls==['x_soul']


def test_all_existing_candidates_precede_alias():
    s=FakeSyllabus({'x_soul':record('x_soul','note'),'x_soal':record('x_soal')})
    assert resolve_details('x_soul (1)',s)=={'namak':'x_soul','suffix':''}
    assert not any(name.endswith('_soal') for name in s.calls)


def test_exact_qa_kind_must_agree_with_canonical_suffix():
    s=FakeSyllabus({'x_pasokh':record('x_pasokh','soal')})
    with pytest.raises(SchemaError,match='KIND_SUFFIX_MISMATCH'):
        resolve_details('x_pasokh',s)
    assert s.calls==['x_pasokh']


@pytest.mark.parametrize('error',[SchemaError('EMPTY_SYLLABUS_RECORD'),AmbiguousError('x',[])])
def test_non_notfound_error_never_triggers_alias(error):
    s=FakeSyllabus({'x_soul':error,'x_soal':record('x_soal')})
    with pytest.raises(type(error)):resolve_details('x_soul',s)
    assert s.calls==['x_soul']

@pytest.mark.parametrize('kind',['note','pasokh'])
def test_alias_cannot_resolve_to_wrong_kind(kind):
    s=FakeSyllabus({'x_soal':record('x_soal',kind)})
    with pytest.raises(NotFoundError):resolve_details('x_soul',s)

@pytest.mark.parametrize('aliases',[{'soul':['soal','pasokh']},{'soul':'soal','SOUL':'pasokh'}])
def test_ambiguous_alias_is_blocked(aliases):
    s=FakeSyllabus({'x_soal':record('x_soal'),'x_pasokh':record('x_pasokh','pasokh')},aliases)
    with pytest.raises(AmbiguousError):resolve_details('x_soul',s)

@pytest.mark.parametrize('separator',['_','-',' '])
def test_alias_is_only_a_separated_final_word(separator):
    s=FakeSyllabus({'x_soal':record('x_soal')})
    assert resolve_details('x'+separator+'soul',s)['namak']=='x_soal'
    for name in ('xsoul','x_soul_extra','x_soal_typo'):
        with pytest.raises(NotFoundError):resolve_details(name,s)


def test_canonical_spelling_is_preserved_in_output():
    name='Persian\u200cName with_space_soal'
    assert to_output_name(name)=='LessonNote_hard_Persian\u200cName_with_space_soal_v01.pdf'


def test_output_collision_still_blocks_alias(real,tmp_path):
    first=resolve_details('shimi_physic_20_soal',real)
    claimed={to_output_name(first['namak']).casefold()}
    result=app.process_job([tmp_path/'shimi_physic_20_soul.pdf'],None,real,real.config,tmp_path,claimed)
    assert result['status_code']=='BLOCKED'
    assert 'نام خروجی یکسان' in result['error']


def test_dry_run_kind_and_no_processing(real,tmp_path,monkeypatch,capsys):
    for name in ('shimi_physic_20_soul','shimi_physic_20_pasokh','shimi_physic_20'):
        (tmp_path/(name+'.pdf')).write_bytes(b'dry run must not read PDF contents')
    monkeypatch.setattr(app,'Syllabus',lambda:real)
    monkeypatch.setattr(app,'process_job',lambda *a,**kw:pytest.fail('dry run processed a PDF'))
    assert app.main(['--dry-run','--input',str(tmp_path)])==0
    lines=[line for line in capsys.readouterr().out.splitlines() if line.startswith('MATCH |')]
    assert len(lines)==3
    assert {line.rsplit(' | ',1)[-1] for line in lines}=={'note','soal','pasokh'}
    assert any('shimi_physic_20_soul.pdf | shimi_physic_20_soal |' in line for line in lines)
