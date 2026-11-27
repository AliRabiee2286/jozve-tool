"""Q4 grammar, glyph refusal, exact plain-text routing and real Story raster tests."""
from pathlib import Path
import pymupdf as fitz
import pytest
from formula import render_formula_html,FormulaGlyphError,FormulaSyntaxError
from syllabus import load_config,discover_assets
from formula_proof import make_proof
from scan_formulas import scan_workbook
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def dependencies():
    cfg=load_config(ROOT/'config.yaml')
    return {'settings':cfg['qa']['formula'], 'font':fitz.Font(fontfile=str(discover_assets(cfg,ROOT,roles=['font'])['font']))}

@pytest.mark.parametrize('source,inner',[
    ('e^x','e<sup>x</sup>'),('e^{2x}','e<sup>2x</sup>'),
    ('x_{1}','x<sub>1</sub>'),('x^{2}_{3}','x<sup>2</sup><sub>3</sub>'),
    ('x_1','x<sub>1</sub>')])
def test_formula_grammar(source,inner,dependencies):
    html,report=render_formula_html(source,**dependencies)
    assert '<span dir="ltr"' in html and inner in html
    assert report['formula'] and report['spans']==[{'start':0,'end':len(source),'source':source}]
    assert report['glyphs_checked']>0

@pytest.mark.parametrize('text',['','متن فارسی','زوج/فرد','XRD','SEM','K-NN','آشنایی با شعر معاصر/ نیما','In','ریشه واژه','خط\nدوم',' {متن} ','☃'])
def test_plain_text_routes_unchanged(text,dependencies):
    html,report=render_formula_html(text,**dependencies)
    assert html is None and not report['formula'] and report['spans']==[]

@pytest.mark.parametrize('text',['x^{2','x^{{2}}','x^{a^{b}}','x^','x^}','x^{}','x^{2}}','x^2^3','x_{1}_{2}'])
def test_malformed_scripts_are_not_guessed(text,dependencies):
    with pytest.raises(FormulaSyntaxError) as exc:render_formula_html(text,**dependencies)
    assert exc.value.code.startswith('FORMULA_')

@pytest.mark.parametrize('char',list('√²³₂π∑'))
def test_missing_math_glyph_is_explicit(char,dependencies):
    with pytest.raises(FormulaGlyphError) as exc:render_formula_html(char,**dependencies)
    assert exc.value.code=='FORMULA_GLYPH_MISSING' and exc.value.char==char
    with pytest.raises(FormulaGlyphError):render_formula_html('e^{'+char+'}',**dependencies)


def test_persian_and_latin_text_not_corrected(dependencies):
    text='  توابع In وe^x، حل معادلات لگاریتمی  '
    html,report=render_formula_html(text,**dependencies)
    assert html.startswith('  توابع In و<span')
    assert html.endswith('</span>، حل معادلات لگاریتمی  ')
    assert report['spans'][0]['source']=='e^x'


def test_printed_surrounding_text_is_also_glyph_checked(dependencies):
    with pytest.raises(FormulaGlyphError) as exc:
        render_formula_html('☃ e^x',**dependencies)
    assert exc.value.char=='☃'


def test_html_metacharacters_are_escaped(dependencies):
    class AllGlyphs:
        def has_glyph(self,code,**kwargs):return 1
    html,_=render_formula_html('<b>& e^{2<x}',settings=dependencies['settings'],font=AllGlyphs())
    assert html.startswith('&lt;b&gt;&amp; ')
    assert '<sup>2&lt;x</sup>' in html


def test_unbraced_script_is_one_atom(dependencies):
    html,report=render_formula_html('e^xy',**dependencies)
    assert 'e<sup>x</sup></span>y' in html
    assert report['spans'][0]['source']=='e^x'


def test_real_story_sup_sub_and_font():
    proof=make_proof()
    assert proof['aria_only'] and proof['dpi']==150
    boxes=proof['script_ink_pixels']
    assert boxes['superscript'][1]<boxes['sup_plain'][1]
    assert boxes['superscript'][3]<boxes['sup_plain'][3]
    assert boxes['subscript'][3]>boxes['sub_plain'][3]


def test_all_workbook_display_cells():
    result=scan_workbook()
    assert not result['errors']
    assert len(result['formula_cells'])==3
    assert {v['sheet'] for v in result['formula_cells']}=={'فیزیک','فیزیک-سوال','فیزیک-پاسخ'}
    assert all([span['source'] for span in v['report']['spans']]==['e^x'] for v in result['formula_cells'])
    assert result['plain_cells']>0
