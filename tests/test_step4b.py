"""Regression evidence for exact assembly rendering and footer detection."""
import json
from pathlib import Path
import pymupdf as fitz
import pytest
from syllabus import load_config
from pages import number_matches, number_candidates, remove_numbers
from main import write_report

ROOT=Path(__file__).resolve().parents[1]
CFG=load_config()


@pytest.mark.parametrize('text',[
    '1','Page 3','صفحه ۱۲','New Section 1 Page 3','elminoastp 1 Page 1',
    'a b c Page 2','abc صفحه ۳','New Section 1'])
def test_number_pattern_accepts_footer(text):
    assert number_matches(text,CFG['pages'])


@pytest.mark.parametrize('text',[
    'Wednesday, April 15, 2026 4:31 PM','a b c d Page 2',
    'Page 3 explains this problem','This is content','12 April 2026'])
def test_number_pattern_preserves_other_lines(text):
    assert not number_matches(text,CFG['pages'])


def test_removal_band_and_post_fit_qc_band():
    with fitz.open() as doc:
        p=doc.new_page(width=600,height=800)
        p.insert_text((60,710),'elminoastp 1 Page 1',fontsize=10)
        p.insert_text((60,770),'New Section 1 Page 3',fontsize=10)
        p.insert_text((60,790),'Wednesday, April 15, 2026 4:31 PM',fontsize=10)
        removed=remove_numbers(p,CFG['pages'])
        assert [r['text'] for r in removed]==['New Section 1 Page 3']
        assert 'Wednesday, April 15, 2026 4:31 PM' in p.get_text()
        assert not number_candidates(p,CFG['pages'])
        assert [r['text'] for r in number_candidates(p,
            {**CFG['pages'],'bottom_fraction':CFG['pages']['qc_bottom_fraction']})]==['elminoastp 1 Page 1']


def test_nojoom_three_pages_and_exact_saved_assembly():
    report=json.loads((ROOT/CFG['paths']['output']/'report.json').read_text(encoding='utf-8'))
    items={item['namak']:item for item in report['items']}
    item=items['nojoom_astr_18']
    assert item['status']=='موفق' and item['input_pages']==3
    assert all(any('Page' in r['text'] for r in p['removed']) for p in item['pages'])
    with fitz.open(ROOT/CFG['paths']['output']/item['output']) as doc:
        assert all('Page' not in p.get_text() for p in list(doc)[1:])
    for item in report['items']:
        measurements=[d['detail'] for d in item['qc']['details'] if d['check'].endswith('رندر پس از مونتاژ')]
        assert len(measurements)==item['input_pages']
        assert all(d['different_pixels']==0 and d['same_shape'] for d in measurements)
        assert all(item['qc']['checks'].values())
    for key in ('physics_mech_7','ECONO EC M 12'):
        assert any(e['pixels_over_10']>0 for e in items[key]['output_intents_effect'])


def test_image_warning_is_one_summary_per_file(tmp_path):
    item={'files':['example.pdf'],'status':'موفق','warnings':[
        {'kind':'image_number_unknown','page':1},
        {'kind':'image_number_unknown','page':1},
        {'kind':'image_number_unknown','page':3}]}
    write_report(tmp_path,[item],[])
    text=(tmp_path/'report.txt').read_text(encoding='utf-8-sig')
    assert text.count('شمارهٔ تصویری نامعلوم:')==1
    assert '2 صفحه' in text and 'ماهیت تصویر نامعلوم' in text
