import pytest
from qa_cover_sweep import run_sweep
pytestmark=pytest.mark.slow

def test_all_real_qa_covers():
    result=run_sweep(artifacts=True)
    assert result['complete']
    assert result['ok']+result['empty']==result['total']
    assert result['errors']==0
    assert all(r['error_type']=='CoverError' and 'EMPTY_SYLLABUS_RECORD' in r['error']
               for r in result['results'] if r['status']=='empty')
