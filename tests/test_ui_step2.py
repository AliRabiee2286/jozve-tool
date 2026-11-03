"""Stage 2 contracts for terminal modes and English-only terminal output."""
from io import StringIO
from pathlib import Path
import re
import shutil

from events import EventBus
import main as app
import ui as ui_module
from ui import TerminalUI, select_mode, write_ui_previews


ARABIC = re.compile(r'[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]')


class TTY(StringIO):
    def isatty(self):
        return True


def test_auto_mode_selects_fancy_compat_or_plain_safely():
    modern = {'WT_SESSION': '1'}
    old_cmd = {}
    assert select_mode('auto', stream=TTY(), environ=modern, rich_available=True) == 'fancy'
    assert select_mode('auto', stream=TTY(), environ=old_cmd, rich_available=True) == 'compat'
    assert select_mode('auto', stream=StringIO(), environ=modern, rich_available=True) == 'plain'
    assert select_mode('auto', stream=TTY(), environ=modern, rich_available=True,
                       no_color=True) == 'plain'
    assert select_mode('auto', stream=TTY(), environ=modern, rich_available=False) == 'plain'
    assert select_mode('compat', stream=StringIO(), environ={}, rich_available=False) == 'compat'


def test_plain_events_are_short_english_and_hide_persian_details():
    stream = StringIO()
    bus = EventBus()
    ui = TerminalUI('plain', stream=stream, quiet=False)
    ui.attach(bus)
    bus.emit('run_started')
    bus.emit('file_started', file='درس.pdf', index=1, total=1)
    bus.emit('warning', file='درس.pdf', kind='empty_cover_fields', message='مقدار خالی')
    bus.emit('stage_started', file='درس.pdf', stage='pages')
    bus.emit('stage_progress', file='درس.pdf', stage='pages', index=1, total=2)
    bus.emit('error', file='درس.pdf', stage='resolve', message='نامک در سیلابس پیدا نشد')
    bus.emit('file_done', file='درس.pdf', status='خطا', status_code='BLOCKED',
             item={'namak': 'درس', 'sheet': 'فیزیک', 'orientation': 'portrait',
                   'input_pages': 2, 'seconds': 1.2})
    bus.emit('run_finished', counts={'OK': 0, 'REVIEW': 0, 'BLOCKED': 1},
             summary='خلاصه فارسی', interrupted=False)
    output = stream.getvalue()
    assert not ARABIC.search(output)
    assert 'E101' in output and 'namak not found in syllabus' in output
    assert 'FAIL' in output and 'BLOCKED=1' in output


def test_compat_mode_uses_ascii_status_words():
    stream = StringIO()
    bus = EventBus()
    ui = TerminalUI('compat', stream=stream)
    ui.attach(bus)
    bus.emit('file_started', file='example.pdf', index=1, total=1)
    bus.emit('warning', file='example.pdf', kind='advisory', message='هشدار')
    bus.emit('file_done', file='example.pdf', status='موفق', status_code='OK',
             item={'namak': 'example', 'sheet': 'Physics', 'orientation': 'landscape',
                   'input_pages': 3, 'seconds': 2.0})
    bus.emit('run_finished', counts={'OK': 1, 'REVIEW': 0, 'BLOCKED': 0},
             summary='', interrupted=False)
    output = stream.getvalue()
    assert not ARABIC.search(output)
    assert 'PASS' in output and 'Summary:' in output
    assert '✓' not in output and '✗' not in output


def test_fancy_mode_uses_live_dashboard_on_a_modern_tty():
    stream = TTY()
    bus = EventBus()
    ui = TerminalUI('fancy', stream=stream, environ={'WT_SESSION': '1'})
    assert ui.mode == 'fancy'
    ui.attach(bus)
    ui.start()
    bus.emit('file_started', file='example.pdf', index=1, total=1)
    bus.emit('stage_progress', file='example.pdf', stage='pages', index=1, total=1)
    bus.emit('file_done', file='example.pdf', status_code='OK', status='موفق',
             item={'sheet': 'Physics', 'orientation': 'portrait', 'input_pages': 1,
                   'output_pages': 2}, seconds=0.1)
    bus.emit('run_finished', counts={'OK': 1, 'REVIEW': 0, 'BLOCKED': 0},
             total_seconds=0.1)
    ui.close()
    output = stream.getvalue()
    assert not ARABIC.search(output)
    assert all(part in output for part in ('JO', 'ZVE', 'TOOL', 'Files', 'Report:'))


def test_missing_rich_and_no_color_never_break_plain_output():
    stream = StringIO()
    ui = TerminalUI('auto', stream=stream, environ={'NO_COLOR': '1'},
                    rich_available=False)
    assert ui.mode == 'plain'
    ui.emit_summary({'OK': 1, 'REVIEW': 0, 'BLOCKED': 0}, total_seconds=0.1)
    assert not ARABIC.search(stream.getvalue())


def test_import_error_for_rich_falls_back_to_plain(monkeypatch):
    monkeypatch.setattr(ui_module, '_rich_modules', lambda: None)
    ui = TerminalUI('auto', stream=TTY(), environ={'WT_SESSION': '1'})
    assert ui.mode == 'plain'


def test_preview_writer_creates_fake_and_real_style_svg_files(tmp_path):
    paths = write_ui_previews(tmp_path)
    assert {path.name for path in paths} == {
        'fake_fancy.svg', 'fake_compat.svg', 'real_fancy.svg', 'real_compat.svg'
    }
    assert all(path.read_text(encoding='utf-8').startswith('<svg') for path in paths)


def test_main_plain_startup_error_has_no_persian_on_terminal(tmp_path, capsys):
    output = Path(__file__).resolve().parents[1] / 'tests' / '.ui_step2_cli'
    shutil.rmtree(output, ignore_errors=True)
    try:
        code = app.main(['--ui', 'plain', '--input', str(tmp_path / 'missing.pdf'),
                         '--output', str(output)])
        captured = capsys.readouterr()
        assert code == 1
        assert not ARABIC.search(captured.out + captured.err)
        assert 'E201' in captured.out
    finally:
        shutil.rmtree(output, ignore_errors=True)


def test_ctrl_c_returns_130_and_does_not_publish_partial_pdf(tmp_path, monkeypatch, capsys):
    output = Path(__file__).resolve().parents[1] / 'tests' / '.ui_step2_interrupt'
    shutil.rmtree(output, ignore_errors=True)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(app, 'process_job', interrupt)
    try:
        code = app.main(['--ui', 'plain', '--input', str(Path(__file__).resolve().parents[1] /
                         'tests/data/cli_inputs/physics_thermo_8.pdf'),
                         '--output', str(output)])
        captured = capsys.readouterr()
        assert code == 130
        assert 'Interrupted' in captured.out
        assert not ARABIC.search(captured.out + captured.err)
        assert not list(output.glob('*.pdf'))
    finally:
        shutil.rmtree(output, ignore_errors=True)
