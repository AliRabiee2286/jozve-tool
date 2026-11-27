import json
import pymupdf as fitz
import pytest

import pages
from bake_review import REASON, publish_with_bake_review
from report_html import write_html_report
from report_text import write_report
from syllabus import load_config


def _annotated_document():
    doc = fitz.open()
    page = doc.new_page(width=240, height=320)
    page.draw_rect(fitz.Rect(10, 10, 230, 310), color=(0, 0, 0))
    annot = page.add_highlight_annot(fitz.Rect(30, 60, 120, 80))
    annot.set_opacity(1)
    annot.update()
    doc.xref_set_key(annot.xref, 'BM', 'null')
    doc.new_page(width=20, height=20)
    return doc


def test_structural_review_publication_has_three_same_run_images_and_reports(tmp_path, monkeypatch):
    with _annotated_document() as doc:
        original_raster = pages.raster
        calls = {}

        def injected_raster(page, *args, **kwargs):
            image = original_raster(page, *args, **kwargs)
            calls[page.number] = calls.get(page.number, 0) + 1
            if page.number == 0 and calls[page.number] == 2:
                image[0, 0, 0] -= 6
            return image

        monkeypatch.setattr(pages, 'raster', injected_raster)
        staged = tmp_path / 'stage'
        records = pages.bake_annotations(doc, load_config()['pages'], review_dir=staged)
        assert records[0]['max_channel_difference'] == 6
        assert records[0]['review']['reason'] == REASON
        assert records[1]['max_channel_difference'] == 0

        intermediate = staged / 'review.pdf'
        doc.save(intermediate)
        output = tmp_path / 'output'
        output.mkdir()
        page_report = [{'page': i+1, 'bake': row, 'removed': []}
                       for i, row in enumerate(records)]
        published = publish_with_bake_review(intermediate, output, page_report)
        assert len(published) == 1
        assert published[0]['page'] == 1
        assert published[0]['max_channel_difference'] == 6
        assert published[0]['reason'] == REASON
        assert (output / 'review.pdf').is_file()
        assert set(published[0]['images']) == {'before', 'after', 'diff'}
        for path in published[0]['images'].values():
            assert (output / path).is_file()

        item = {'files': ['review.pdf'], 'status': 'بازبینی', 'status_code': 'REVIEW',
                'output': 'review.pdf', 'pages': page_report, 'bake_review_pages': published,
                'qc': {'checks': {}, 'blocking_failed': [], 'advisory_failed': []}}
        write_report(output, [item], [])
        text = (output / 'REVIEW.txt').read_text(encoding='utf-8-sig')
        assert REASON in text and 'max_channel_difference' not in text
        assert 'bake_p0001_before.png' in text
        report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
        assert report['counts'] == {'OK': 0, 'REVIEW': 1, 'BLOCKED': 0}
        html = write_html_report(output, [item], [], thumbs='none').read_text(encoding='utf-8')
        assert REASON in html
        for path in published[0]['images'].values():
            assert path in html
        archive = next((output / 'reports').glob('*/report.html')).read_text(encoding='utf-8')
        assert '../../review/' in archive


def test_review_switch_off_keeps_raster_failure_blocked(monkeypatch, tmp_path):
    with _annotated_document() as doc:
        original_raster = pages.raster
        calls = {}

        def injected_raster(page, *args, **kwargs):
            image = original_raster(page, *args, **kwargs)
            calls[page.number] = calls.get(page.number, 0) + 1
            if page.number == 0 and calls[page.number] == 2:
                image[0, 0, 0] -= 6
            return image

        monkeypatch.setattr(pages, 'raster', injected_raster)
        settings = dict(load_config()['pages'], bake_structural_review=False)
        with pytest.raises(ValueError, match='Bake verification failed'):
            pages.bake_annotations(doc, settings, review_dir=tmp_path)


def test_review_publish_collision_preserves_previous_evidence(tmp_path):
    stage = tmp_path / 'stage'
    output = tmp_path / 'output'
    (stage / 'bake_p0001_before.png').parent.mkdir(parents=True)
    (stage / 'bake_p0001_before.png').write_bytes(b'new before')
    for label in ('after', 'diff'):
        (stage / f'bake_p0001_{label}.png').write_bytes(b'new ' + label.encode())
    (stage / 'review.pdf').write_bytes(b'new pdf')
    target = output / 'review' / 'review_bake_p0001_before.png'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'old review image')
    pages = [{'page': 1, 'bake': {'max_channel_difference': 6,
              'review': {'reason': REASON, 'images': {'before': 'bake_p0001_before.png',
                         'after': 'bake_p0001_after.png', 'diff': 'bake_p0001_diff.png'}}}}]
    with pytest.raises(FileExistsError, match='Bake REVIEW evidence already exists'):
        publish_with_bake_review(stage / 'review.pdf', output, pages)
    assert target.read_bytes() == b'old review image'
    assert (stage / 'review.pdf').read_bytes() == b'new pdf'
    assert (stage / 'bake_p0001_before.png').read_bytes() == b'new before'


@pytest.mark.parametrize('mutation,reason', [
    ('stream', 'original content streams changed'),
    ('group', 'group changed'),
    ('output_intent', 'output_intents changed'),
    ('blend', 'AP stream, Group or graphic state changed'),
    ('stroke_alpha', 'AP stream, Group or graphic state changed'),
    ('annotation', 'annotations remain'),
])
def test_clean_proof_and_tampered_structure(mutation, reason):
    import bake_proof

    with _annotated_document() as doc:
        evidence = bake_proof.snapshot(doc[0])
        doc.bake(annots=True, widgets=False)
        assert bake_proof.verify(doc[0], evidence)['ap_calls'] == 1
        page = doc[0]
        if mutation == 'stream':
            ref = evidence['content_refs'][0]
            doc.update_stream(ref, doc.xref_stream(ref) + b'\n% tampered\n')
        elif mutation == 'group':
            doc.xref_set_key(page.xref, 'Group', '<</S/Transparency/I true>>')
        elif mutation == 'output_intent':
            doc.xref_set_key(doc.pdf_catalog(), 'OutputIntents', '[<</S/GTS_PDFA1/Info(tampered)>>]')
        elif mutation == 'annotation':
            page.add_rect_annot(fitz.Rect(20, 20, 30, 30))
        else:
            stream = doc.xref_stream(page.get_contents()[-1])
            name, _ = next(bake_proof._calls(stream))
            form = int(doc.xref_get_key(page.xref, f'Resources/XObject/{name}')[1].split()[0])
            key, value = ('BM', '/Normal') if mutation == 'blend' else ('CA', '0.5')
            doc.xref_set_key(form, f'Resources/ExtGState/H/{key}', value)
        with pytest.raises(bake_proof.Unproved, match=reason):
            bake_proof.verify(doc[0], evidence)


@pytest.mark.parametrize('unsupported', ['rotation', 'matrix'])
def test_unsupported_geometry_has_no_proof(unsupported):
    import bake_proof

    with _annotated_document() as doc:
        page = doc[0]
        if unsupported == 'rotation':
            page.set_rotation(90)
        else:
            annot = next(page.annots())
            form = int(doc.xref_get_key(annot.xref, 'AP/N')[1].split()[0])
            doc.xref_set_key(form, 'Matrix', '[2 0 0 1 0 0]')
        with pytest.raises(bake_proof.Unproved, match='unsupported'):
            bake_proof.snapshot(page)
