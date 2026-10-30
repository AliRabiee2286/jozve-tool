"""QC must reject corrupted output and ink hidden underneath a correct border."""
import pymupdf as fitz
import pytest
from syllabus import Syllabus
from cover import build_cover
from pages import process_pages, _preserve_rendering_attributes
from qc import check_pdf
from naamak import to_output_name


@pytest.fixture
def example(tmp_path):
    record=Syllabus().find('physics_thermo_8')
    source=fitz.open();p=source.new_page(width=600,height=800);p.insert_text((70,90),'Content')
    cover,cr=build_cover(record['template_index'],'portrait',{f:record[f] for f in ('teacher','course','chapter','topic')})
    content,pr=process_pages(source)
    result=fitz.open(stream=cover.tobytes(),filetype='pdf');result.insert_pdf(content)
    _preserve_rendering_attributes(content,result,1,preserve_catalog=False)
    path=tmp_path/to_output_name(record['namak'])
    yield source,record,cover,cr,pr,result,path
    result.close();content.close();cover.close();source.close()


def check(example):
    source,record,cover,cr,pr,result,path=example
    result.save(path)
    return check_pdf(path,source,record,cr,pr,cover)


def test_valid_saved_document(example):
    assert check(example)['passed']


def test_hidden_ink_is_detected(example):
    source,record,cover,cr,pr,result,path=example
    page=result[1];streams=page.get_contents()
    # Add a black mark beneath the header to the existing content stream. It is
    # invisible behind the overlaid border, but stripped-border QC must find it.
    region=pr['pages'][0]['pieces'][0]['bbox']
    x=region[0]+20;y=region[1]+5
    command=f'\nq 0 0 0 rg {x} {page.rect.height-y-5} 5 5 re f Q\n'.encode('ascii')
    result.update_stream(streams[0],command+result.xref_stream(streams[0]))
    quality=check(example)
    assert not quality['passed']
    assert quality['checks']['صفحه محتوا 1: جوهر زیر نوارها صفر'] is False


def test_extra_cover_mark_is_rejected(example):
    example[5][0].draw_rect(fitz.Rect(5,5,15,15),fill=(0,0,0))
    quality=check(example)
    assert not quality['passed']
    assert not quality['checks']['رندر فرست‌پیج فقط در چهار ناحیه']
