from diff_syllabus import compare_rows
from diff_syllabus import sheet_records
from types import SimpleNamespace


def row(value):
    return [{'row':1,'record':{'field':value}}]


def test_diff_add_remove_change_and_unchanged():
    result=compare_rows({'removed':row('a'),'changed':row('old'),'same':row('x')},
                        {'added':row('b'),'changed':row('new'),'same':row('x')},['field'])
    assert set(result['added'])=={'added'}
    assert set(result['removed'])=={'removed'}
    assert result['changed']['changed']['fields']==['field']
    assert set(result['changed'])=={'changed'}
    assert not result['ambiguous']


def test_duplicate_records_are_reported_not_selected():
    result=compare_rows({'key':row('a')+row('b')},{'key':row('a')},['field'])
    assert set(result['ambiguous'])=={'key'}
    assert not result['changed']


def test_legacy_diff_excludes_new_qa_sheets():
    syllabus=SimpleNamespace(
        config={'sheet_to_template':{'legacy':1},'fallback_sheet':'video'},
        column_map={'legacy':{},'video':{},'qa':{}},
        _index={'a':[{'row':1,'record':{'sheet':'legacy'}}],
                'b':[{'row':1,'record':{'sheet':'qa','kind':'question'}}]},
        _fallback_index={'c':[{'row':1,'record':{'sheet':'video'}}]})
    result=sheet_records(syllabus)
    assert set(result)=={'legacy','video'}
    assert set(result['legacy'])=={'a'} and set(result['video'])=={'c'}
