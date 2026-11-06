"""HTML reports: offline resources, real thumbnails, legacy compatibility, archives."""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
import re
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
                if tag == 'a' and key == 'href':
                    assert attrs[key].startswith(('#', './review.pdf')) or attrs[key] in (
                        'https://github.com/AliRabiee86',
                        'https://github.com/AliRabiee2286/jozve-tool'), (tag, attrs)
                else:
                    assert attrs[key].startswith(('#', 'data:')), (tag, attrs)
    # External navigation was explicitly requested; resources remain embedded.
    assert 'connect-src \'none\'' in html
    assert all(token in html for token in
               ('prefers-color-scheme', 'prefers-reduced-motion', '@media print',
                'data-status="REVIEW"', 'data-count=', 'aria-live='))


def test_report_embeds_configured_aria_and_allows_it_through_csp(tmp_path, items):
    from report_html import PROJECT_ROOT, write_html_report
    from syllabus import load_config

    config = load_config()
    font = next((PROJECT_ROOT / config['paths']['assets']).glob(config['asset_patterns']['font']))
    html = write_html_report(tmp_path, items, [], thumbs='none', config=config).read_text(encoding='utf-8')
    encoded = html.split('data:font/otf;base64,', 1)[1].split(')', 1)[0]
    assert base64.b64decode(encoded, validate=True) == font.read_bytes()
    assert 'font-src data:' in html
    assert 'local("Times New Roman")' in html
    assert 'unicode-range:U+0000-024F,U+1E00-1EFF' in html
    assert 'font-family:ReportLatin,ReportAria,Tahoma,sans-serif' in html


def test_all_subject_icons_are_embedded_monochrome_and_decorative(tmp_path, items):
    import report_html
    from syllabus import load_config
    subjects = load_config()['field_labels_en']
    assert len(subjects) == 14
    for subject in subjects:
        icon = report_html._subject_icon({'sheet': subject})
        attrs = ReportParser(icon).elements[0][1]
        assert attrs['aria-hidden'] == 'true'
        assert attrs['class'] == 'subject-icon'
        encoded = attrs['style'].split('base64,')[1].split(')')[0]
        with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as image:
            assert image.mode == 'RGBA'
            assert image.getchannel('A').getextrema() == (0, 255)
        assert encoded != report_html._BALATAR_LOGO_PNG
    assert report_html._BALATAR_LOGO_PNG in report_html._subject_icon({'sheet': '<unknown>'})
    html = report_html.write_html_report(tmp_path, items, [], thumbs='none').read_text(encoding='utf-8')
    parser = ReportParser(html)
    icons = [attrs for tag, attrs in parser.elements if tag == 'svg' and attrs.get('class') != 'github-icon']
    assert len(icons) == 6
    assert all(attrs['aria-hidden'] == 'true' and attrs['focusable'] == 'false' for attrs in icons)
    assert 'mask:var(--subject-image)' in html
    assert 'pointer-events:none' in html
    assert '.metric:active' in html and '.metric[aria-pressed="true"]' in html
    assert 'prefers-reduced-motion:reduce' in html
    # Item count must not be overridden by the former fixed-column rules.
    for selector in ('metrics', 'properties', 'thumbnails', 'qc-grid', 'detail-grid'):
        declarations = re.findall(r'(?:^|[{}])\s*\.' + selector + r'\{([^{}]*)\}', html)
        assert declarations
        assert all('grid-template-columns:' not in rule for rule in declarations)
    assert 'repeat(auto-fit,minmax(min(100%,var(--cell-min)),1fr))' in html
    assert '.metric:hover:not(:active)' in html


def test_subject_color_follows_each_file_status_and_hero_watermark_stays_subtle(tmp_path, items):
    import report_html
    combinations = []
    for subject in report_html._SUBJECT_KEYS:
        for code in report_html.STATUSES:
            item = deepcopy(items[0])
            item.update(sheet=subject, status_code=code)
            combinations.append(item)
    html = report_html.write_html_report(tmp_path, combinations, [], thumbs='none').read_text(encoding='utf-8')
    elements = ReportParser(html).elements
    for code in report_html.STATUSES:
        cards = [attrs for tag, attrs in elements if tag == 'details' and
                 attrs.get('class') == 'file-card ' + code.lower()]
        assert len(cards) == 14
        assert f'.file-card.{code.lower()}{{--subject-color:var(--{code.lower()})}}' in html
    assert 'background:var(--subject-color,var(--brand))' in html
    hero_rules = re.findall(r'(?:^|[{}])\s*\.hero::after\{([^{}]*)\}', html)
    assert hero_rules
    for rule in hero_rules:
        opacity = re.search(r'opacity:([\d.]+)', rule)
        if opacity:
            assert float(opacity.group(1)) <= .04
    assert 'inset-inline-start:auto' in html


def test_review_buttons_target_correct_pdf_pages_and_work_from_archive(tmp_path, items):
    from urllib.parse import unquote
    from report_html import write_html_report
    item = deepcopy(items[1])
    name = 'lesson # review.pdf'
    shutil.copyfile(tmp_path / 'review.pdf', tmp_path / name)
    item.update(output=name, input_pages=3, output_pages=4)
    item['qc']['advisory_failed'] = ['صفحه محتوا 1: متن حفظ شده', 'صفحه محتوا 3: متن حفظ شده',
                                   'صفحه محتوا 3: هش تصاویر', 'صفحه محتوا 99: نامعتبر']
    path = write_html_report(tmp_path, [item], [], thumbs='none')
    def buttons(path):
        return [attrs for tag, attrs in ReportParser(path.read_text(encoding='utf-8')).elements
                if tag == 'a' and attrs.get('data-pdf-link') == 'true']
    links = buttons(path)
    assert [attrs['href'].split('#page=')[-1] for attrs in links[1:]] == ['2', '4']
    assert len(links) == 3
    for attrs in links:
        assert attrs['target'] == '_blank' and attrs['rel'] == 'noopener noreferrer'
        assert (tmp_path / unquote(attrs['href'].split('#')[0])).resolve() == (tmp_path / name).resolve()
    archive = next((tmp_path / 'reports').glob('*/report.html'))
    for attrs in buttons(archive):
        assert (archive.parent / unquote(attrs['href'].split('#')[0])).resolve() == (tmp_path / name).resolve()


@pytest.mark.parametrize('output_name,status', [('missing.pdf','REVIEW'),('../outside.pdf','REVIEW'),
                                               ('review.pdf','BLOCKED'),('https://example.com/a.pdf','REVIEW')])
def test_review_links_never_publish_missing_blocked_or_external_outputs(tmp_path, items, output_name, status):
    from report_html import _review_links
    item = deepcopy(items[1])
    item.update(output=output_name, status_code=status)
    assert 'data-pdf-link' not in _review_links(item, tmp_path)


def test_footer_credit_links_are_explicit_and_do_not_load_remote_assets(tmp_path, items):
    from report_html import write_html_report
    html = write_html_report(tmp_path, items, [], thumbs='none').read_text(encoding='utf-8')
    elements = ReportParser(html).elements
    links = [attrs for tag, attrs in elements if tag == 'a' and attrs.get('href', '').startswith('https:')]
    assert {attrs['href'] for attrs in links} == {'https://github.com/AliRabiee86',
                                                'https://github.com/AliRabiee2286/jozve-tool'}
    assert all(attrs['target'] == '_blank' and attrs['rel'] == 'noopener noreferrer' for attrs in links)
    assert 'توسعه‌یافته توسط' in html
    assert all(not attrs.get('src', '').startswith(('http:', 'https:')) for _, attrs in elements)


@pytest.mark.parametrize('count', [0, 2])
def test_report_rejects_missing_or_ambiguous_font(tmp_path, monkeypatch, count):
    import report_html
    from syllabus import load_config

    config = load_config()
    monkeypatch.setattr(report_html, 'PROJECT_ROOT', tmp_path)
    assets = tmp_path / config['paths']['assets']
    assets.mkdir()
    for index in range(count):
        (assets / f'{index}-Aria-Regular.otf').write_bytes(b'font')
    with pytest.raises(ValueError, match='exactly one'):
        report_html.write_html_report(tmp_path / 'out', [], [], config=config)
    assert not (tmp_path / 'out' / 'report.html').exists()


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
    assert snapshots[-1].read_text(encoding='utf-8') == path.read_text(encoding='utf-8').replace(
        'data-pdf-link="true" href="./', 'data-pdf-link="true" href="../../')
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


def test_report_failure_does_not_advertise_a_report_link(tmp_path, items, monkeypatch, capsys):
    monkeypatch.setattr(app, 'Syllabus', lambda: SimpleNamespace(warnings=[]))
    monkeypatch.setattr(app, 'discover_assets', lambda *args: {})
    monkeypatch.setattr(app, 'process_job', lambda *args, **kw: deepcopy(items[0]))
    monkeypatch.setattr(app, 'write_html_report', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('HTML unavailable')))
    out = tmp_path / 'result'
    assert app.main(['--input', str(tmp_path / 'review.pdf'), '--output', str(out),
                     '--ui', 'plain', '--no-thumbs']) == 0
    assert 'Report:' not in capsys.readouterr().out


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
