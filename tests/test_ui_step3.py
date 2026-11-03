"""HTML reports: offline resources, real thumbnails, legacy compatibility, archives."""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pymupdf as fitz
import pytest

import main as app
from report_text import write_report


class ReportParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.fixture
def items(tmp_path):
    source = tmp_path / 'review.pdf'
    with fitz.open() as document:
        for index in range(4):
            page = document.new_page(width=600, height=800)
            page.insert_text((100, 100), f'Page content {index}')
        document.save(source)
    ok = {
        'files': ['lesson.pdf'], 'status': 'موفق', 'status_code': 'OK',
        'namak': 'lesson', 'sheet': 'فیزیک', 'orientation': 'portrait',
        'input_pages': 3, 'output_pages': 4, 'seconds': 1.2, 'output': 'review.pdf',
        'cover': {'fields': {'teacher': {'value': 'استاد <script>alert(1)</script>'},
                             'course': {'value': 'درس'}, 'chapter': {'value': None},
                             'topic': {'value': 'مبحث'}}},
        'warnings': [{'kind': 'empty_cover_fields', 'fields': ['chapter']}],
        'pages': [{'page': 1, 'removed': [{'text': 'Page 12'}]}],
        'qc': {'checks': {'باز شدن PDF': True, 'صفحه محتوا 1: متن حفظ شده': True},
               'blocking_failed': [], 'advisory_failed': [], 'details': []},
    }
    review = deepcopy(ok)
    review.update(files=['review.pdf'], status='بازبینی', status_code='REVIEW')
    review['qc']['checks']['صفحه محتوا 1: متن حفظ شده'] = False
    review['qc']['advisory_failed'] = ['صفحه محتوا 1: متن حفظ شده']
    blocked = {'files': ['bad.pdf'], 'status': 'خطا', 'status_code': 'BLOCKED',
               'output': 'review.pdf', 'error': 'نامک پیدا نشد', 'warnings': []}
    return [ok, review, blocked]


def test_report_sections_metadata_and_untrusted_text_are_offline_and_escaped(tmp_path, items):
    from report_html import write_html_report
    log = [
        {'versions': {'python': '3.12', 'pymupdf': '1.28.2'}, 'run_id': 'test-run'},
        {'asset': 'font', 'sha256': '123456789abc', 'message': 'منبع فونت'},
        {'file': 'review.pdf', 'stage': 'qc', 'seconds': .75, 'error': None},
    ]
    (tmp_path / 'log.jsonl').write_text('\n'.join(map(json.dumps, log)), encoding='utf-8')
    before = deepcopy(items)
    path = write_html_report(tmp_path, items, ['هشدار سیلابس'], thumbs='none', elapsed=12.5)
    html = path.read_text(encoding='utf-8')
    parser = ReportParser(html)
    assert ('html', {'lang': 'fa', 'dir': 'rtl'}) in parser.elements
    for text in ('جست‌وجو', 'بازبینی', 'چه کنم', 'بلاک‌کننده', 'توصیه‌ای',
                 'شماره‌های حذف‌شده', 'Page 12', 'مقدار خالی', 'زمان مرحله‌ها',
                 '123456789abc', '3.12', 'test-run', 'نامک پیدا نشد'):
        assert text in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert items == before
    for tag, attrs in parser.elements:
        for key in ('src', 'href', 'action'):
            if key in attrs:
                assert attrs[key].startswith(('#', 'data:')), (tag, attrs)
    assert 'http:' not in html and 'https:' not in html
    assert all(token in html for token in
               ('prefers-color-scheme', 'prefers-reduced-motion', '@media print',
                'data-status="REVIEW"', 'data-count=', 'aria-live='))


@pytest.mark.parametrize('mode,count', [('review', 3), ('all', 6), ('none', 0)])
def test_thumbnails_are_small_jpegs_from_first_three_output_pages_only(tmp_path, items, mode, count):
    from report_html import write_html_report
    pdf = tmp_path / 'review.pdf'
    before = (hashlib.sha256(pdf.read_bytes()).digest(), pdf.stat().st_mtime_ns)
    path = write_html_report(tmp_path, items, [], thumbs=mode)
    images = [attrs for tag, attrs in ReportParser(path.read_text(encoding='utf-8')).elements
              if tag == 'img']
    assert len(images) == count
    for attrs in images:
        assert attrs['src'].startswith('data:image/jpeg;base64,')
        with Image.open(BytesIO(base64.b64decode(attrs['src'].split(',', 1)[1]))) as image:
            assert image.format == 'JPEG' and image.width == 320
    assert (hashlib.sha256(pdf.read_bytes()).digest(), pdf.stat().st_mtime_ns) == before


def test_no_thumbs_and_blocked_files_never_open_even_old_output(tmp_path, items, monkeypatch):
    import report_html
    opened = []

    def forbidden(*args, **kwargs):
        opened.append(args)
        raise AssertionError('Report must not open a PDF in this mode')

    monkeypatch.setattr(report_html.fitz, 'open', forbidden)
    report_html.write_html_report(tmp_path, items, [], thumbs='none')
    path = report_html.write_html_report(tmp_path, [items[-1]], [], thumbs='all')
    assert '<img ' not in path.read_text(encoding='utf-8')
    assert opened == []


def test_missing_output_and_empty_or_interrupted_run_still_have_reports(tmp_path, items):
    from report_html import write_html_report
    items[1]['output'] = 'missing.pdf'
    path = write_html_report(tmp_path, [items[1]], [])
    assert 'پیش‌نمایش موجود نیست' in path.read_text(encoding='utf-8')
    path = write_html_report(tmp_path, [], [], interrupted=True)
    html = path.read_text(encoding='utf-8')
    assert 'متوقف شد' in html and 'فایلی برای نمایش وجود ندارد' in html


@pytest.mark.skipif(shutil.which('node') is None, reason='Node is optional for inline JavaScript checks')
@pytest.mark.parametrize('motion', ['reduce', 'animate'])
def test_real_inline_script_filters_and_opens_details(tmp_path, items, motion):
    from report_html import write_html_report
    path = write_html_report(tmp_path, items, [], thumbs='none')
    script = Path(__file__).with_name('report_html_dom_test.cjs')
    result = subprocess.run(['node', str(script), str(path), motion], capture_output=True,
                            text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_archive_keeps_twenty_managed_runs_and_preserves_legacy_reports(tmp_path, items):
    from report_html import write_html_report
    root = tmp_path / 'reports'
    for number in range(23):
        old = root / f'20261001_000000_{number:06d}'
        old.mkdir(parents=True)
        (old / 'report.html').write_text('old', encoding='utf-8')
    foreign = root / 'manual'
    foreign.mkdir()
    legacy = {'report.txt': b'\xef\xbb\xbflegacy', 'report.json': b'{"items":[]}'}
    for name, data in legacy.items():
        (tmp_path / name).write_bytes(data)
    path = write_html_report(tmp_path, items, [], thumbs='none',
                             now=datetime(2026, 11, 3, 12, 0, 0))
    snapshots = sorted(root.glob('*/report.html'))
    assert len(snapshots) == 20 and foreign.is_dir()
    assert snapshots[-1].read_bytes() == path.read_bytes()
    for name, data in legacy.items():
        assert (tmp_path / name).read_bytes() == data
        assert (snapshots[-1].parent / name).read_bytes() == data


def test_cli_no_thumbs_preserves_text_and_json_format(tmp_path, items, monkeypatch, capsys):
    monkeypatch.setattr(app, 'Syllabus', lambda: SimpleNamespace(warnings=[]))
    monkeypatch.setattr(app, 'discover_assets', lambda *args: {})
    monkeypatch.setattr(app, 'process_job', lambda *args, **kw: deepcopy(items[0]))
    out = tmp_path / 'result'
    assert app.main(['--input', str(tmp_path / 'review.pdf'), '--output', str(out),
                     '--ui', 'plain', '--no-thumbs']) == 0
    assert '<img ' not in (out / 'report.html').read_text(encoding='utf-8')
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    expected = tmp_path / 'legacy'
    expected.mkdir()
    write_report(expected, report['items'], [])
    for name in ('report.txt', 'report.json'):
        assert (out / name).read_bytes() == (expected / name).read_bytes()
    assert not any('\u0600' <= char <= '\u06ff' for char in capsys.readouterr().out)


def test_report_failure_does_not_change_pdf_success(tmp_path, items, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError('test HTML failure')

    monkeypatch.setattr(app, 'Syllabus', lambda: SimpleNamespace(warnings=[]))
    monkeypatch.setattr(app, 'discover_assets', lambda *args: {})
    monkeypatch.setattr(app, 'process_job', lambda *args, **kw: deepcopy(items[0]))
    monkeypatch.setattr(app, 'write_html_report', fail)
    out = tmp_path / 'result'
    assert app.main(['--input', str(tmp_path / 'review.pdf'), '--output', str(out),
                     '--ui', 'plain', '--thumbs', 'all']) == 0
    assert 'HTML report unavailable' in capsys.readouterr().out
    assert 'test HTML failure' in (out / 'log.txt').read_text(encoding='utf-8')


def test_failed_html_publish_keeps_previous_report_and_cleans_own_temp(tmp_path, items, monkeypatch):
    import report_html
    previous = tmp_path / 'report.html'
    previous.write_bytes(b'previous report')

    def fail(*args, **kwargs):
        raise PermissionError('file is open')

    monkeypatch.setattr(report_html.os, 'replace', fail)
    with pytest.raises(PermissionError):
        report_html.write_html_report(tmp_path, items, [], thumbs='none')
    assert previous.read_bytes() == b'previous report'
    assert not list(tmp_path.glob('.report_*.html'))
