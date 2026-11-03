"""Self-contained Persian HTML reports; PDFs are opened read-only after processing."""
import base64
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
from string import Template
import tempfile

import pymupdf as fitz

from syllabus import load_config


STATUSES = {'OK': 'موفق', 'REVIEW': 'بازبینی', 'BLOCKED': 'خطا'}
STAGES = {'resolve': 'تطبیق سیلابس', 'cover': 'فرست‌پیج', 'border': 'بوردر',
          'pages': 'صفحات', 'qc': 'کنترل کیفیت', 'write': 'انتشار'}


def _text(value):
    return escape(str(value if value is not None else 'ثبت نشده'), quote=True)


def _code(item):
    code = item.get('status_code')
    if code in STATUSES:
        return code
    return {'موفق': 'OK', 'بازبینی': 'REVIEW'}.get(item.get('status'), 'BLOCKED')


def _badge(code):
    return f'<span class="badge {code.lower()}">{STATUSES[code]} <bdi>{code}</bdi></span>'


def _run_data(output):
    data = {'versions': {}, 'assets': {}, 'stages': {}, 'run_id': 'ثبت نشده'}
    log = output / 'log.jsonl'
    if log.is_file():
        with log.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                data['run_id'] = record.get('run_id', data['run_id'])
                data['versions'].update(record.get('versions', {}))
                if record.get('asset'):
                    data['assets'][record['asset']] = record.get('sha256', 'ثبت نشده')
                if record.get('stage') in STAGES and record.get('seconds') is not None:
                    data['stages'].setdefault(record.get('file', ''), []).append(record)
    return data


def _thumbnails(output, item, config):
    path = (output / item.get('output', '')).resolve()
    if not item.get('output') or not path.is_relative_to(output.resolve()) or not path.is_file():
        return '<p class="muted">پیش‌نمایش موجود نیست؛ فایل خروجی در دسترس نیست.</p>'
    settings = config['reports']
    figures = []
    try:
        with fitz.open(path) as document:
            for index in range(min(3, len(document))):
                page = document[index]
                scale = settings['thumbnail_width'] / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False,
                                     colorspace=fitz.csRGB)
                image = base64.b64encode(pix.tobytes('jpeg', jpg_quality=settings['jpeg_quality'])).decode('ascii')
                caption = 'فرست‌پیج' if index == 0 else f'صفحهٔ محتوای {index}'
                figures.append(f'<figure><img src="data:image/jpeg;base64,{image}" '
                               f'width="{pix.width}" height="{pix.height}" loading="lazy" '
                               f'alt="{caption}"><figcaption>{caption}</figcaption></figure>')
    except Exception:
        return '<p class="muted">پیش‌نمایش موجود نیست؛ بازکردن یا رندر PDF ناموفق بود.</p>'
    return '<div class="thumbnails">' + ''.join(figures) + '</div>'


def _qc_html(item, config):
    quality = item.get('qc', {})
    groups = {'بلاک‌کننده': [], 'توصیه‌ای': []}
    blocking = set(config['qc']['blocking'])
    for name, passed in quality.get('checks', {}).items():
        short = name.split(': ', 1)[1] if name.startswith('صفحه محتوا ') and ': ' in name else name
        required = short in blocking or name in quality.get('blocking_failed', [])
        result = 'قبول' if passed else 'رد'
        groups['بلاک‌کننده' if required else 'توصیه‌ای'].append(
            f'<li><span class="check {"passed" if passed else "failed"}">{result}</span>'
            f'<span>{_text(name)}</span></li>')
    if not any(groups.values()):
        return '<p class="muted">کنترل کیفیت انجام نشده است.</p>'
    html = ''.join(f'<div><h4>{label}</h4><ul class="checks">{"".join(rows)}</ul></div>'
                   for label, rows in groups.items())
    if quality.get('details'):
        raw = json.dumps(quality['details'], ensure_ascii=False, indent=2)
        html += f'<details class="technical"><summary>جزئیات فنی QC</summary><pre>{_text(raw)}</pre></details>'
    return html


def _warnings_html(item, config):
    messages = []
    for warning in item.get('warnings', []):
        kind = warning.get('kind')
        if kind == 'empty_cover_fields':
            fields = '، '.join(config['headers'].get(key, [key])[-1] for key in warning['fields'])
            message = 'مقدار خالی در سیلابس: ' + fields
        elif kind == 'image_number_unknown':
            message = f"صفحهٔ {warning.get('page', 'نامعلوم')}: تصویر کوچک پایین صفحه؛ ماهیت آن نامعلوم است و حذف نشد."
        elif kind == 'syllabus_source_conflict':
            message = 'تعارض سیلابس: مقدار شیت رشته‌ای معتبر است.'
        elif kind == 'widgets_preserved':
            message = f"صفحهٔ {warning.get('page', 'نامعلوم')}: فیلدهای فرم حفظ شدند."
        elif kind == 'review_image_error':
            message = 'ساخت تصویر مرور ناموفق بود: ' + str(warning.get('detail', ''))
        else:
            message = json.dumps(warning, ensure_ascii=False)
        messages.append('<li>' + _text(message) + '</li>')
    return '<ul>' + ''.join(messages) + '</ul>' if messages else '<p class="muted">هشداری ثبت نشده است.</p>'


def _file_html(item, index, output, config, metadata, thumbs):
    code = _code(item)
    files = ', '.join(item.get('files', []))
    name = item.get('namak') or files
    orientation = {'portrait': 'عمودی', 'landscape': 'افقی'}.get(item.get('orientation'), 'ثبت نشده')
    seconds = item.get('seconds', 0)
    page_text = f"{item.get('input_pages', '—')} ← {item.get('output_pages', '—')}"
    cells = (f'<a href="#file-{index}" data-open="file-{index}"><bdi>{_text(name)}</bdi></a>',
             _text(item.get('sheet')), orientation, page_text, f'{seconds:.2f} ثانیه', _badge(code))
    row = f'<tr data-status="{code}" data-file="file-{index}">' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr>'
    properties = [('نامک', item.get('namak')), ('فایل ورودی', files), ('رشته', item.get('sheet'))]
    fields = item.get('cover', {}).get('fields', {})
    for key in config['cover']['fields']:
        field = fields.get(key, {})
        value = field.get('value', 'ثبت نشده')
        if 'value' in field and (value is None or not str(value).strip()):
            value = 'مقدار خالی در سیلابس'
        properties.append((config['headers'][key][-1], value))
    properties += [('جهت', orientation), ('صفحات ورودی ← خروجی', page_text),
                   ('فایل خروجی', item.get('output') if code != 'BLOCKED' else 'منتشر نشده'),
                   ('زمان پردازش', f'{seconds:.2f} ثانیه')]
    info = '<dl class="properties">' + ''.join(
        f'<div><dt>{_text(label)}</dt><dd><bdi>{_text(value)}</bdi></dd></div>' for label, value in properties) + '</dl>'
    action = ''
    if code == 'REVIEW':
        action = '<aside class="notice review"><h3>چه کنم؟</h3><p>فایل منتشر شده است. کنترل‌های توصیه‌ای ردشده و پیش‌نمایش‌ها را ببینید و صفحات مربوط را در PDF بازبینی کنید.</p></aside>'
    elif code == 'BLOCKED':
        action = f'<aside class="notice blocked"><h3>خروجی منتشر نشد</h3><p>{_text(item.get("error", "علت ثبت نشده"))}</p><p>علت خطا را اصلاح و دوباره اجرا کنید. خروجی قدیمی، نتیجهٔ این اجرا نیست.</p></aside>'
    removed = ''.join(f'<li>صفحهٔ {_text(page.get("page"))}: <bdi>{_text(number.get("text"))}</bdi></li>'
                      for page in item.get('pages', []) for number in page.get('removed', []))
    removed = '<ul>' + removed + '</ul>' if removed else '<p class="muted">شمارهٔ متنی حذف‌شده‌ای ثبت نشده است.</p>'
    timing = metadata['stages'].get(files, [])
    timings = ''.join(f'<li><span>{STAGES[entry["stage"]]}</span><bdi>{entry["seconds"]:.4f} ثانیه</bdi></li>' for entry in timing)
    timings = '<ul class="timings">' + timings + '</ul>' if timings else '<p class="muted">زمان مرحله‌ها ثبت نشده است.</p>'
    images = ''
    if code != 'BLOCKED' and (thumbs == 'all' or thumbs == 'review' and code == 'REVIEW'):
        images = '<section><h3>مرور صفحات</h3>' + _thumbnails(output, item, config) + '</section>'
    opened = ' open' if code in ('REVIEW', 'BLOCKED') else ''
    detail = (f'<details class="file-card {code.lower()}" id="file-{index}" data-status="{code}"{opened}>'
              f'<summary><span class="file-title"><span class="ordinal">{index:02d}</span><bdi>{_text(name)}</bdi></span>{_badge(code)}</summary>'
              f'<div class="file-body">{action}{info}{images}<section><h3>کنترل کیفیت</h3><div class="qc-grid">{_qc_html(item, config)}</div></section>'
              f'<div class="detail-grid"><section><h3>هشدارها</h3>{_warnings_html(item, config)}</section>'
              f'<section><h3>شماره‌های حذف‌شده</h3>{removed}</section><section><h3>زمان مرحله‌ها</h3>{timings}</section></div></div></details>')
    return row, detail


def _archive(output, html, now, retain):
    root = output / 'reports'
    archive = root / now.strftime('%Y%m%d_%H%M%S_%f')
    archive.mkdir(parents=True, exist_ok=False)
    (archive / 'report.html').write_text(html, encoding='utf-8', newline='\n')
    for name in ('report.txt', 'report.json', 'log.txt', 'log.jsonl'):
        if (output / name).is_file():
            shutil.copyfile(output / name, archive / name)
    managed = sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink()
                     and re.fullmatch(r'\d{8}_\d{6}_\d{6}', path.name) and (path / 'report.html').is_file())
    for directory in managed[:-retain]:
        shutil.rmtree(directory)


def write_html_report(output, items, global_warnings, *, thumbs='review', elapsed=0,
                      interrupted=False, config=None, now=None):
    """Publish a UTF-8 HTML report and archive it without mutating items or PDFs."""
    if thumbs not in ('review', 'all', 'none'):
        raise ValueError('Invalid thumbnail mode')
    config = load_config() if config is None else config
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now().astimezone()
    metadata = _run_data(output)
    counts = {code: sum(_code(item) == code for item in items) for code in STATUSES}
    total = len(items)
    percent = round(counts['OK'] / total * 100) if total else 0
    cards = ''.join(f'<button class="metric {code.lower()}" data-filter="{code}" aria-pressed="false">'
                    f'<span class="metric-label">{label}</span><strong data-count="{counts[code]}">{counts[code]}</strong>'
                    f'<span class="metric-caption">{caption}</span></button>'
                    for code, label, caption in (
                        ('OK', 'موفق', 'آمادهٔ تحویل'), ('REVIEW', 'بازبینی', 'منتشرشده؛ نیازمند مرور'),
                        ('BLOCKED', 'خطا', 'منتشرنشده')))
    rows, details = [], []
    for index, item in enumerate(items, 1):
        row, detail = _file_html(item, index, output, config, metadata, thumbs)
        rows.append(row)
        details.append(detail)
    warnings = ('<aside class="global-warnings"><h2>هشدارهای سیلابس</h2><ul>' +
                ''.join('<li>' + _text(warning) + '</li>' for warning in global_warnings) + '</ul></aside>') if global_warnings else ''
    versions = ' · '.join(f'<bdi>{_text(key)} {_text(value)}</bdi>' for key, value in metadata['versions'].items()) or 'ثبت نشده'
    assets = ''.join(f'<li><bdi>{_text(role)}</bdi><code>{_text(sha)}</code></li>' for role, sha in metadata['assets'].items())
    html = Template(HTML_TEMPLATE).substitute(
        date=_text(now.strftime('%Y/%m/%d · %H:%M:%S %z')), run_id=_text(metadata['run_id']),
        heading='اجرا متوقف شد' if interrupted else 'گزارش آماده است.',
        intro='اجرای شما متوقف شد؛ فقط نتایج ثبت‌شدهٔ این اجرا در گزارش آمده‌اند.' if interrupted else 'از نتیجهٔ اجرا تا جزئیات هر جزوه؛ همه در یک نگاه.',
        total=total, elapsed=f'{elapsed:.2f}', percent=percent, cards=cards, warnings=warnings,
        rows=''.join(rows), details=''.join(details), empty=' hidden' if items else '',
        versions=versions, assets=assets or '<li>ثبت نشده</li>', tool_version=_text(config['tool_version']))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         prefix='.report_', suffix='.html', dir=output, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(html)
        target = output / 'report.html'
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    _archive(output, html, now, config['reports']['retain_runs'])
    return target


HTML_TEMPLATE = r'''<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>گزارش پردازش جزوه‌ها | جزوه‌تول</title>
<style>
:root{--bg:#f4f5f1;--surface:#fff;--soft:#eef2ed;--ink:#203b36;--muted:#5f726b;--line:#dbe3dc;--brand:#176a53;--brand-soft:#e1efe5;--ok:#176844;--ok-bg:#e6f2e8;--review:#805819;--review-bg:#fff1d3;--blocked:#a23535;--blocked-bg:#fbe8e6;--shadow:0 10px 38px #243d3210;--radius:20px;color-scheme:light}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI",Tahoma,Arial,sans-serif;font-size:15px;line-height:1.9}
button,input,select{font:inherit}button,a,input,select,summary{-webkit-tap-highlight-color:transparent}button,summary,select{cursor:pointer}button{color:inherit}a{color:var(--brand);text-decoration-thickness:1px;text-underline-offset:4px}a:hover{text-decoration:none}bdi,code{overflow-wrap:anywhere}button:focus-visible,a:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--brand);outline-offset:4px}[hidden]{display:none!important}
.topbar{border-bottom:1px solid var(--line);background:var(--surface)}.topbar-inner{max-width:1184px;padding:20px 24px;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{display:flex;align-items:center;gap:12px}.brand-mark{width:38px;height:38px;border-radius:12px;background:var(--brand);color:var(--surface);display:grid;place-items:center;font:700 24px Georgia,serif}.brand strong{font-size:13px;letter-spacing:2px}.brand small{display:block;color:var(--muted);font-size:12px}.print-button{background:transparent;border:1px solid var(--line);border-radius:10px;padding:7px 16px}.print-button:hover{background:var(--soft)}
main{max-width:1184px;padding:42px 24px 64px;margin:auto}.eyebrow{color:var(--brand);font-size:12px;letter-spacing:1px;font-weight:700}.hero{display:grid;grid-template-columns:1fr 295px;gap:40px;align-items:center;margin-bottom:30px}.hero h1{font-size:clamp(30px,4vw,48px);font-weight:750;line-height:1.55;letter-spacing:-1.3px;margin:12px 0}.hero p{color:var(--muted);font-size:16px;margin:8px 0}.run-meta{display:flex;gap:10px 24px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:20px}.run-meta span{display:flex;align-items:center;gap:7px}.local-dot{display:inline-block;width:7px;height:7px;background:var(--ok);border-radius:50%}
.completion{display:flex;gap:20px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:24px;box-shadow:var(--shadow)}.ring{--percent:$percent;width:110px;height:110px;flex-shrink:0;border-radius:50%;background:conic-gradient(var(--brand) calc(var(--percent)*1%),var(--soft) 0);padding:9px;position:relative;transform:rotate(0deg)}.ring-inside{width:100%;height:100%;border-radius:50%;background:var(--surface);display:grid;place-content:center;text-align:center}.ring-inside strong{font:700 28px "Segoe UI",sans-serif;line-height:1.2}.ring-inside small{font-size:10px;color:var(--muted)}.completion-title{font-weight:700;font-size:14px}.completion-caption{font-size:12px;color:var(--muted);line-height:1.7;margin-top:6px}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:0 0 40px}.metric{border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);padding:22px 25px;text-align:right;display:grid;grid-template-columns:1fr auto;column-gap:12px;position:relative;overflow:hidden;transition:transform .2s,border-color .2s,box-shadow .2s}.metric::before{content:"";position:absolute;inset:23px 0 23px auto;width:4px;border-radius:8px;background:currentColor}.metric:hover{transform:translateY(-3px);box-shadow:var(--shadow)}.metric[aria-pressed="true"]{border-color:currentColor;box-shadow:inset 0 0 0 1px currentColor}.metric.ok{color:var(--ok)}.metric.review{color:var(--review)}.metric.blocked{color:var(--blocked)}.metric-label{font-weight:700}.metric strong{grid-column:2;grid-row:1/3;align-self:center;font-size:38px;line-height:1.3;font-variant-numeric:tabular-nums}.metric-caption{font-size:12px;color:var(--muted)}
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}.section-heading h2{font-size:21px;margin:0}.section-heading p{font-size:12px;color:var(--muted);margin:0}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:20px}.search-box{flex:1;min-width:220px}.toolbar label{display:block;color:var(--muted);font-size:12px;margin:0 3px 5px}.toolbar input,.toolbar select{width:100%;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink);padding:10px 14px;min-height:46px}.toolbar input::placeholder{color:var(--muted)}.filter-box{min-width:185px}
.table-shell{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:auto;box-shadow:var(--shadow);margin-bottom:30px}table{width:100%;border-collapse:collapse;white-space:nowrap;text-align:right}caption{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}th{font-size:12px;font-weight:600;color:var(--muted);background:var(--soft);padding:13px 18px}td{border-top:1px solid var(--line);padding:16px 18px;font-size:13px}tbody tr:hover{background:var(--soft)}td:first-child{font-weight:600;max-width:360px;white-space:normal}td a{display:block;min-width:160px}.badge{display:inline-flex;align-items:center;gap:8px;padding:4px 11px;border-radius:8px;white-space:nowrap;font-size:11px;font-weight:650}.badge::before{content:"";width:6px;height:6px;background:currentColor;border-radius:50%}.badge.ok{color:var(--ok);background:var(--ok-bg)}.badge.review{color:var(--review);background:var(--review-bg)}.badge.blocked{color:var(--blocked);background:var(--blocked-bg)}.badge bdi{font-size:10px;font-weight:500}
.global-warnings{border:1px solid var(--line);border-radius:14px;padding:16px 22px;margin-bottom:28px;font-size:13px}.global-warnings h2{font-size:14px;margin:0}.global-warnings ul{margin:6px 0 0;padding-right:20px}.file-card{border:1px solid var(--line);border-radius:var(--radius);background:var(--surface);margin-bottom:14px;overflow:hidden}.file-card>summary{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:20px 24px;list-style:none}.file-card>summary::-webkit-details-marker{display:none}.file-title{display:flex;align-items:center;gap:14px;min-width:0;font-weight:650;font-size:14px}.file-title::after{content:"+";color:var(--muted);font:400 20px monospace}.file-card[open]>.file-title::after{content:"−"}.file-card[open]>summary .file-title::after{content:"−"}.ordinal{font-size:11px;color:var(--muted);font-weight:500;font-variant-numeric:tabular-nums}.file-card.review{border-right:4px solid var(--review)}.file-card.blocked{border-right:4px solid var(--blocked)}.file-body{padding:0 24px 24px;border-top:1px solid var(--line)}.file-body h3{font-size:14px;margin:24px 0 12px}.file-body h4{font-size:12px;color:var(--muted);margin:10px 0}.properties{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin:24px 0}.properties>div{min-width:0}.properties dt{font-size:11px;color:var(--muted);margin-bottom:5px}.properties dd{margin:0;font-size:13px;line-height:1.9}.properties dd bdi{white-space:pre-wrap}.notice{border-radius:12px;padding:15px 20px;margin-top:20px;font-size:13px}.notice h3{margin:0 0 6px}.notice p{margin:5px 0}.notice.review{background:var(--review-bg);color:var(--review)}.notice.blocked{background:var(--blocked-bg);color:var(--blocked)}
.thumbnails{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;background:var(--soft);padding:20px;border-radius:14px}.thumbnails figure{margin:0;min-width:0;text-align:center}.thumbnails img{display:block;max-width:100%;max-height:340px;width:auto;height:auto;margin:auto;object-fit:contain;box-shadow:0 4px 18px #0002;border-radius:4px;background:#fff}.thumbnails figcaption{font-size:11px;color:var(--muted);margin-top:12px}.qc-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.checks{list-style:none;padding:0;margin:0;max-height:350px;overflow:auto;border:1px solid var(--line);border-radius:12px}.checks li{display:flex;align-items:baseline;gap:10px;padding:9px 12px;font-size:12px;border-bottom:1px solid var(--line)}.checks li:last-child{border:0}.check{font-size:10px;padding:1px 7px;border-radius:5px;flex-shrink:0}.check.passed{color:var(--ok);background:var(--ok-bg)}.check.failed{color:var(--blocked);background:var(--blocked-bg)}.technical{grid-column:1/-1;font-size:12px;color:var(--muted)}pre{direction:ltr;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;background:var(--soft);padding:16px;border-radius:10px;max-height:350px;overflow:auto;font-size:11px}.detail-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:24px}.detail-grid section{min-width:0}.detail-grid ul{font-size:12px;padding-right:18px}.timings{list-style:none;padding:0!important}.timings li{display:flex;justify-content:space-between;gap:15px;border-bottom:1px dotted var(--line);padding:5px 0}.muted{color:var(--muted);font-size:12px}.empty{text-align:center;padding:35px;border:1px dashed var(--line);border-radius:14px;color:var(--muted)}
footer{border-top:1px solid var(--line);padding-top:25px;margin-top:35px;color:var(--muted);font-size:11px;display:grid;grid-template-columns:1.5fr 1fr;gap:24px}footer h2{font-size:12px;color:var(--ink);margin:0 0 8px}footer p{margin:5px 0}.assets{list-style:none;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:4px 22px}.assets li{display:flex;justify-content:space-between;gap:8px}.assets code{font-size:10px}.footer-note{margin-top:18px!important}
@keyframes appear{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}.hero,.metrics,.results{animation:appear .5s both}.metrics{animation-delay:.06s}.results{animation-delay:.12s}
@media(prefers-color-scheme:dark){:root{--bg:#121e1b;--surface:#1b2a25;--soft:#24382f;--ink:#e0ebe3;--muted:#b2c3b7;--line:#385043;--brand:#93d4b0;--brand-soft:#293e31;--ok:#a5d9b6;--ok-bg:#223f30;--review:#eac382;--review-bg:#463823;--blocked:#f1aaaa;--blocked-bg:#472a2a;--shadow:0 10px 38px #0002;color-scheme:dark}.brand-mark{color:var(--bg)}}
@media(max-width:800px){main{padding-top:28px}.hero{grid-template-columns:1fr;gap:20px}.completion{max-width:none;justify-content:center}.metrics{gap:10px}.metric{padding:18px}.metric strong{font-size:30px}.metric-caption{font-size:10px}.properties{grid-template-columns:1fr 1fr}.detail-grid{grid-template-columns:1fr}.section-heading{align-items:flex-start}footer{grid-template-columns:1fr}}
@media(max-width:520px){.topbar-inner,main{padding-right:16px;padding-left:16px}.metrics{grid-template-columns:1fr}.metric{grid-template-columns:1fr auto;padding:15px 22px}.metric strong{font-size:32px}.metric-caption{font-size:12px}.toolbar{display:block}.filter-box{margin-top:12px}.qc-grid{grid-template-columns:1fr}.thumbnails{grid-template-columns:1fr}.file-card>summary{padding:18px 14px;gap:10px}.file-body{padding:0 16px 20px}.file-title{font-size:12px;gap:8px}.badge{font-size:10px;padding:4px 8px}.badge bdi{display:none}.section-heading{display:block}.assets{grid-template-columns:1fr}}
@media print{:root{--bg:#fff;--surface:#fff;--soft:#f4f4f4;--ink:#111;--muted:#444;--line:#ccc;--brand:#176a53;--ok:#176844;--ok-bg:#f4f4f4;--review:#805819;--review-bg:#f4f4f4;--blocked:#a23535;--blocked-bg:#f4f4f4}body{background:#fff!important;color:#111!important;font-size:11px}.topbar,.toolbar,.print-button,.ring,.technical{display:none!important}main{max-width:none;padding:0}.hero{display:block;margin-bottom:12px}.hero h1{font-size:22px}.completion{display:none}.metrics{margin-bottom:14px}.metric{padding:10px 16px;box-shadow:none}.metric strong{font-size:24px}.file-card,.table-shell{box-shadow:none;border-color:#ccc}.file-body{display:block!important}.checks{max-height:none;overflow:visible}.checks li{break-inside:avoid}.thumbnails{background:#fff;break-inside:avoid}.thumbnails img{max-height:180px}.detail-grid{gap:12px}.badge{border:1px solid #999}.hero,.results{animation:none}footer{break-inside:avoid}.file-title::after{display:none}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>
</head>
<body>
<header class="topbar"><div class="topbar-inner"><div class="brand"><span class="brand-mark" aria-hidden="true">J</span><div><strong dir="ltr">JOZVE TOOL</strong><small>گزارش پردازش جزوه‌ها</small></div></div><button type="button" class="print-button" id="print-report">چاپ گزارش</button></div></header>
<main>
<section class="hero" aria-labelledby="report-heading"><div><div class="eyebrow">گزارش اجرا / آفلاین</div><h1 id="report-heading">$heading</h1><p>$intro</p><div class="run-meta"><span><i class="local-dot" aria-hidden="true"></i>ذخیره‌شده روی دستگاه</span><span><time dir="ltr">$date</time></span><span>$total فایل · $elapsed ثانیه</span></div></div><div class="completion"><div class="ring" role="img" aria-label="$percent درصد فایل‌ها بدون نیاز به بازبینی موفق شدند"><div class="ring-inside"><strong><span data-count="$percent">$percent</span>٪</strong><small>موفق بدون بازبینی</small></div></div><div><div class="completion-title">وضعیت این اجرا</div><div class="completion-caption">خلاصه را ببینید؛<br>جزئیات هر فایل پایین‌تر است.</div></div></div></section>
<section class="metrics" aria-label="خلاصه و فیلتر وضعیت">$cards</section>
$warnings
<section class="results" aria-labelledby="results-heading"><div class="section-heading"><h2 id="results-heading">نتیجهٔ فایل‌ها</h2><p id="results-count" aria-live="polite">$total فایل در این اجرا</p></div>
<div class="toolbar"><div class="search-box"><label for="search">جست‌وجو در فایل‌ها و اطلاعات جزوه</label><input id="search" type="search" placeholder="نامک، درس یا نام استاد…" autocomplete="off"></div><div class="filter-box"><label for="status-filter">وضعیت فایل</label><select id="status-filter"><option value="all">همهٔ فایل‌ها</option><option value="OK">موفق</option><option value="REVIEW">نیازمند بازبینی</option><option value="BLOCKED">خطا</option></select></div></div>
<div class="table-shell"><table><caption>خلاصهٔ نتیجهٔ پردازش هر فایل؛ برای جزئیات روی نامک بزنید</caption><thead><tr><th scope="col">نامک / فایل</th><th scope="col">رشته</th><th scope="col">جهت</th><th scope="col">ورودی ← خروجی</th><th scope="col">زمان</th><th scope="col">وضعیت</th></tr></thead><tbody>$rows</tbody></table></div>
<p class="empty" id="empty"$empty>فایلی برای نمایش وجود ندارد.</p>
<div class="section-heading"><h2>جزئیات و بازبینی</h2><p>روی عنوان هر فایل بزنید</p></div>
<div id="file-details">$details</div></section>
<footer><div><h2>دربارهٔ این اجرا</h2><p>نسخهٔ ابزار: <bdi>$tool_version</bdi></p><p>شناسهٔ اجرا: <bdi>$run_id</bdi></p><p>زمان پردازش و آماده‌سازی: $elapsed ثانیه</p><p>$versions</p><p class="footer-note">این گزارش خودکفاست؛ برای مشاهدهٔ آن به اینترنت نیاز ندارید.</p></div><div><h2>اثر انگشت منابع · SHA256 کوتاه</h2><ul class="assets">$assets</ul></div></footer>
</main>
<script>
(() => {
  'use strict';
  const search = document.getElementById('search');
  const filter = document.getElementById('status-filter');
  const rows = Array.from(document.querySelectorAll('tbody tr[data-file]'));
  const cards = Array.from(document.querySelectorAll('[data-filter]'));
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const number = new Intl.NumberFormat('fa-IR');
  const normalize = value => value.normalize('NFKC').toLowerCase().replace(/ي/g,'ی').replace(/ك/g,'ک').replace(/\u200c/g,'').replace(/[\s_-]+/g,' ').trim();
  const entries = rows.map(row => {
    const detail = document.getElementById(row.dataset.file);
    return {row, detail, search: normalize(row.textContent + ' ' + detail.textContent)};
  });
  function applyFilter() {
    const query = normalize(search.value);
    let visible = 0;
    entries.forEach(entry => {
      const show = (filter.value === 'all' || entry.row.dataset.status === filter.value) && entry.search.includes(query);
      entry.row.hidden = entry.detail.hidden = !show;
      if (show) visible += 1;
    });
    cards.forEach(card => card.setAttribute('aria-pressed', String(filter.value === card.dataset.filter)));
    document.getElementById('results-count').textContent = number.format(visible) + ' فایل از ' + number.format(entries.length);
    document.getElementById('empty').hidden = visible !== 0;
  }
  search.addEventListener('input', applyFilter);
  filter.addEventListener('change', applyFilter);
  cards.forEach(card => card.addEventListener('click', () => {
    filter.value = filter.value === card.dataset.filter ? 'all' : card.dataset.filter;
    applyFilter();
  }));
  document.querySelectorAll('[data-open]').forEach(link => link.addEventListener('click', () => {
    const detail = document.getElementById(link.dataset.open);
    detail.open = true;
    detail.querySelector('summary').focus();
  }));
  document.getElementById('print-report').addEventListener('click', () => window.print());
  const printState = new Map();
  window.addEventListener('beforeprint', () => {
    entries.forEach(entry => { printState.set(entry.detail, entry.detail.open); entry.detail.open = true; });
  });
  window.addEventListener('afterprint', () => {
    printState.forEach((open, detail) => { detail.open = open; });
    printState.clear();
  });
  const counters = Array.from(document.querySelectorAll('[data-count]'));
  if (reducedMotion) {
    counters.forEach(counter => { counter.textContent = number.format(Number(counter.dataset.count)); });
  } else {
    const start = performance.now();
    function animate(now) {
      const progress = Math.min((now - start) / 700, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      counters.forEach(counter => { counter.textContent = number.format(Math.round(Number(counter.dataset.count) * eased)); });
      document.querySelector('.ring').style.setProperty('--percent', String($percent * eased));
      if (progress < 1) requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
  }
  applyFilter();
})();
</script>
</body>
</html>
'''
