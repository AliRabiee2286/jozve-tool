"""Stage 1 contracts for events, logging, page progress, and report compatibility."""
import json
import os

import pymupdf as fitz
import pytest

from border import clean_border as build_clean_border
from events import EVENT_NAMES, EventBus
from logging_setup import RunLogger
from pages import process_pages
from report_text import write_report


@pytest.fixture(scope='module')
def clean_border():
    return build_clean_border()


def test_event_bus_publishes_named_payloads_and_unsubscribes():
    bus = EventBus()
    seen = []

    def receive(payload):
        seen.append(payload)

    bus.subscribe('stage_progress', receive)
    bus.emit('stage_progress', stage='pages', index=2, total=5)
    bus.unsubscribe('stage_progress', receive)
    bus.emit('stage_progress', stage='pages', index=3, total=5)

    assert set(EVENT_NAMES) == {
        'run_started', 'file_started', 'stage_started', 'stage_progress',
        'stage_finished', 'warning', 'error', 'file_done', 'run_finished',
    }
    assert seen == [{'stage': 'pages', 'index': 2, 'total': 5}]


def test_standard_log_has_text_and_jsonl_records_with_warning_deduplication(tmp_path):
    logger = RunLogger(tmp_path, run_id='run-test')
    logger.info('شروع اجرا', file='example.pdf', stage='run')
    logger.warning('هشدار تکراری', file='example.pdf', stage='pages')
    logger.warning('هشدار تکراری', file='example.pdf', stage='pages')
    logger.close()

    text_lines = (tmp_path / 'log.txt').read_text(encoding='utf-8').splitlines()
    json_lines = [json.loads(line) for line in
                  (tmp_path / 'log.jsonl').read_text(encoding='utf-8').splitlines()]
    assert text_lines[0].split(' | ') == [
        text_lines[0].split(' | ')[0], 'INFO', 'run-test', 'example.pdf', 'run', 'شروع اجرا'
    ]
    assert len([line for line in text_lines if 'هشدار تکراری' in line]) == 1
    assert json_lines[0]['run_id'] == 'run-test'
    assert json_lines[-1]['repeat_count'] == 2


def test_process_pages_reports_one_based_progress(clean_border):
    clean_path, _ = clean_border
    progress = []
    with fitz.open() as source:
        source.new_page(width=595, height=842)
        result, _ = process_pages(source, clean_path=clean_path,
                                   progress=lambda index, total: progress.append((index, total)))
        result.close()
    assert progress == [(1, 1)]


def test_report_text_is_byte_compatible_for_a_known_record(tmp_path):
    item = {
        'files': ['example.pdf'],
        'status': 'موفق',
        'namak': 'example',
        'sheet': 'فیزیک',
        'orientation': 'portrait',
        'input_pages': 1,
        'output_pages': 2,
        'seconds': 1.25,
        'output': 'LessonNote_hard_example_v01.pdf',
        'qc': {'checks': {'باز شدن PDF': True}, 'details': []},
        'pages': [{'page': 1, 'removed': [{'text': 'Page 1'}]}],
        'warnings': [],
    }
    write_report(tmp_path, [item], ['هشدار عمومی'])

    expected = (
        'گزارش پردازش جزوه‌ها\n\n'
        'هشدار سیلابس: هشدار عمومی\n\n'
        'موفق: example.pdf\n'
        'نامک: example\n'
        'رشته: فیزیک\n'
        'جهت: عمودی\n'
        'صفحات ورودی: 1\n'
        'صفحات خروجی: 2\n'
        'زمان (ثانیه): 1.25\n'
        'نام خروجی: LessonNote_hard_example_v01.pdf\n'
        '  باز شدن PDF: قبول\n'
        'حذف شمارهٔ متنی صفحه 1: Page 1\n\n'
        'خلاصه: 1 موفق؛ 0 بازبینی؛ 0 خطا | OK=1 REVIEW=0 BLOCKED=0\n'
    )
    expected = expected.replace('\n', os.linesep)
    assert (tmp_path / 'report.txt').read_bytes() == expected.encode('utf-8-sig')


def test_run_logger_records_assets_and_versions(tmp_path):
    asset = tmp_path / 'asset.bin'
    asset.write_bytes(b'asset')
    logger = RunLogger(tmp_path, run_id='run-meta')
    logger.record_assets({'border': asset})
    logger.record_versions({'tool': 'test'})
    logger.close()

    records = [json.loads(line) for line in
               (tmp_path / 'log.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(record.get('asset') == 'border' and record.get('sha256') for record in records)
    assert any(record.get('versions', {}).get('tool') == 'test' for record in records)
