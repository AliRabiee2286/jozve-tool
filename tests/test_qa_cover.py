import hashlib
from pathlib import Path
import numpy as np
import pymupdf as fitz
import pytest
from syllabus import Syllabus,discover_assets,is_empty_value
from qa_cover import QACoverBuilder,build_qa_cover,CoverError,TextFitError
from formula import FormulaGlyphError
from qa_cover_sweep import records
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def data():
    syllabus=Syllabus(ROOT/'config.yaml')
    with QACoverBuilder(ROOT/'config.yaml') as builder:
        builder.settings['page_size_policy'] = 'native'
        yield builder,records(syllabus)

@pytest.mark.parametrize('kind,index',[(kind,index) for kind in ('soal','pasokh') for index in range(1,15)])
def test_all_native_templates(data,kind,index):
    builder,rows=data
    row=next(r for r in rows if r['kind']==kind and r['template_index']==index and not all(is_empty_value(r[f]) for f in builder.settings['fields']))
    values={f:row[f] for f in builder.settings['fields']}
    doc,report=builder.build(kind,index,values)
    try:
        assert (doc[0].rect.width,doc[0].rect.height)==tuple(builder.cfg['qa']['template_pages']['size'])
        assert set(report['fields'])==set(values)
        assert all(report['fields'][f]['value']==v for f,v in values.items())
        source=builder.templates[report['template_page']-1]
        original_fonts={hashlib.sha256(builder.templates.extract_font(f[0])[3]).digest() for f in source.get_fonts(full=True)}
        fonts={hashlib.sha256(doc.extract_font(f[0])[3]).digest() for f in doc[0].get_fonts(full=True)}
        assert fonts-original_fonts=={builder.font_hash}
        dpi=builder.settings['qc_dpi']
        def pixels(page):
            pix=page.get_pixmap(dpi=dpi,alpha=False)
            return np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
        before=pixels(source)
        with fitz.open(stream=doc.tobytes(),filetype='pdf') as reopened:
            after=pixels(reopened[0])
        allowed=np.zeros(before.shape[:2],dtype=bool)
        for field,info in report['fields'].items():
            rect=fitz.Rect(info['region'])
            x0,y0,x1,y1=(rect*(dpi/72)).irect;allowed[y0:y1,x0:x1]=True
            if not info['empty']:
                assert info['scale']>=builder.settings['min_scale']
                assert info['max_word_gap_em']<=builder.settings['max_word_gap_em']
                ink=fitz.Rect(info['ink_bbox']);assert rect.contains(ink)
                if info['lines']==1 or field=='topic':
                    assert rect.x1-ink.x1<=info['font_size']*builder.settings['row_group_em']
                else:
                    assert abs((rect.x0+rect.x1-ink.x0-ink.x1)/2)<=info['font_size']*builder.settings['row_group_em']
        assert np.array_equal(before[~allowed],after[~allowed])
        assert report['pixel_qc']['outside_values']==0
    finally:doc.close()


def test_empty_topic_erases_only_placeholder(data):
    builder,_=data
    doc,report=builder.build('soal',1,{'course':'درس','chapter':'فصل','topic':None})
    try:
        assert report['fields']['topic']['empty'] and report['fields']['topic']['placeholder_erased']
        assert report['pixel_qc']['outside_values']==0
    finally:doc.close()


def test_formula_uses_aria_and_survives_pixel_qc(data):
    builder,rows=data
    marker=builder.cfg['qa']['formula']['superscript_marker']
    row=next(r for r in rows if marker in (r['topic'] or ''))
    doc,report=builder.build(row['kind'],row['template_index'],{f:row[f] for f in builder.settings['fields']})
    try:
        assert report['fields']['topic']['formula']['formula']
        assert report['fields']['topic']['font_embedded']
        assert report['pixel_qc']['outside_values']==0
    finally:doc.close()

@pytest.mark.parametrize('policy,size,code',[
    ('native',(842,595),'LANDSCAPE'),('input',None,'INPUT_SIZE_REQUIRED'),('invalid',None,'UNKNOWN_PAGE_POLICY')])
def test_unsupported_orientation_or_policy_is_explicit(data,policy,size,code):
    builder,_=data
    with pytest.raises(CoverError,match=code):builder.build('soal',1,{'course':'x','chapter':'y','topic':'z'},policy,input_size=size)


def test_teacher_and_completely_empty_record_are_rejected(data):
    builder,_=data
    with pytest.raises(CoverError,match='THREE_FIELDS'):builder.build('soal',1,{'teacher':'never','course':'x','chapter':'y','topic':'z'})
    with pytest.raises(CoverError,match='EMPTY_SYLLABUS_RECORD'):builder.build('soal',1,{'course':None,'chapter':' ','topic':''})


def test_overflow_does_not_lower_minimum(data):
    builder,_=data
    with pytest.raises(TextFitError):builder.build('soal',1,{'course':'متن بسیار بلند '*1000,'chapter':'y','topic':'z'})


def test_missing_glyph_is_not_replaced(data):
    builder,_=data
    with pytest.raises(FormulaGlyphError):builder.build('soal',1,{'course':'√','chapter':'y','topic':'z'})


def test_public_builder_returns_independent_document():
    doc,report=build_qa_cover('soal',1,{'course':'درس','chapter':'فصل','topic':'مبحث'},'native')
    try:
        assert report['page_size_policy']=='native'
        assert doc[0].get_pixmap().width>0
    finally:doc.close()


@pytest.mark.parametrize('kind', ['soal', 'pasokh'])
@pytest.mark.parametrize('width_ratio', [1, 0.85])
def test_multiline_topic_is_right_aligned(data, kind, width_ratio):
    builder, rows = data
    record = max((r for r in rows if r['kind'] == kind), key=lambda r: len(r['topic'] or ''))
    page_index, (_, regions, _) = builder._template(kind, record['template_index'])
    row = dict(regions[-1], region=list(regions[-1]['region']))
    rect = fitz.Rect(row['region'])
    row['region'][0] = rect.x1 - rect.width * width_ratio
    layer, info = builder._fit(record['topic'], row, builder.settings['max_lines'][-1], builder.templates[page_index].rect, True)
    with fitz.open(stream=layer, filetype='pdf') as doc:
        pix = doc[0].get_pixmap(dpi=builder.settings['qc_dpi'], alpha=False)
        pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        ink = np.any(pixels[:, :, :3] < 240, axis=2)
    size = info['font_size']
    top = row['origin'][1] - size * builder.settings['baseline_em']
    height = size * builder.settings['line_height']
    factor = builder.settings['qc_dpi'] / 72
    rect = fitz.Rect(row['region'])
    edges = []
    for index in range(info['lines']):
        y0, y1 = (round((top + i * height) * factor) for i in (index, index + 1))
        _, xs = np.where(ink[y0:y1])
        assert len(xs)
        edges.append((xs.min() / factor, (xs.max() + 1) / factor))
    tolerance = size * builder.settings['row_group_em']
    assert len(edges) > 1
    assert all(abs(rect.x1-right)<=tolerance for left,right in edges)
    assert edges[-1][1]-edges[-1][0]<rect.width-tolerance


@pytest.mark.parametrize('text', ['متن کوتاه', 'متن فارسی XRD و SEM', 'فرمول e^x', 'خط اول\nخط دوم'])
def test_justify_short_mixed_and_explicit_lines(data, text):
    builder, _ = data
    doc, report = builder.build('soal', 1, {'course': 'درس', 'chapter': 'فصل', 'topic': text})
    try:
        info = report['fields']['topic']
        assert info['value'] == text
        assert report['pixel_qc']['outside_values'] == 0
        rect, ink = fitz.Rect(info['region']), fitz.Rect(info['ink_bbox'])
        assert rect.contains(ink)
        if info['lines']==1:
            assert rect.x1 - ink.x1 <= info['font_size'] * builder.settings['row_group_em']
        else:
            assert rect.x1-ink.x1<=info['font_size']*builder.settings['row_group_em']
        # Short paragraphs and explicit line endings must retain their natural spacing.
        previous_alignment = builder.settings['story_alignment']
        try:
            builder.settings['story_alignment'] = 'center' if info['lines']>1 else 'left'
            natural, _ = builder.build('soal', 1, {'course': 'درس', 'chapter': 'فصل', 'topic': text})
            try:
                assert doc[0].get_pixmap(dpi=150,clip=rect).samples == natural[0].get_pixmap(dpi=150,clip=rect).samples
            finally:
                natural.close()
        finally:
            builder.settings['story_alignment'] = previous_alignment
    finally:
        doc.close()


@pytest.mark.parametrize('kind', ['soal', 'pasokh'])
def test_formula_first_line_has_no_excessive_pixel_gaps(data, kind):
    builder, rows = data
    record = next(r for r in rows if r['kind'] == kind and '^' in (r['topic'] or ''))
    page_index, (_, regions, _) = builder._template(kind, record['template_index'])
    row = regions[-1]
    layer, info = builder._fit(record['topic'], row, builder.settings['max_lines'][-1], builder.templates[page_index].rect, True)
    with fitz.open(stream=layer, filetype='pdf') as doc:
        pix = doc[0].get_pixmap(dpi=builder.settings['qc_dpi'], alpha=True)
        alpha = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, -1]
    size = info['font_size']; factor = builder.settings['qc_dpi'] / 72
    top = row['origin'][1] - size * builder.settings['baseline_em']
    y0, y1 = round(top * factor), round((top + size * builder.settings['line_height']) * factor)
    occupied = np.flatnonzero(np.any(alpha[y0:y1] > 0, axis=0))
    largest_gap = (np.diff(occupied).max() - 1) / factor
    assert largest_gap <= size * builder.settings['max_word_gap_em']
    assert info['scale'] >= builder.settings['min_scale']
