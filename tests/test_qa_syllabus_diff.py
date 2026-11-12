from diff_syllabus import compare_rows


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
