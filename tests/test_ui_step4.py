"""Stage 4: diagnostic startup, read-only dry runs, CLI switches, and exit codes."""
from copy import deepcopy
from io import StringIO
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

import main as app
from syllabus import NotFoundError, load_config, normalize_key

ROOT = Path(__file__).resolve().parents[1]
ARABIC = re.compile(r'[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]')


@pytest.fixture
def local_run(tmp_path, monkeypatch):
    source = tmp_path / 'lesson (1).pdf'
    source.write_bytes(b'Not a PDF: a dry run must never open it')
    config = load_config()
    sheet, template = next(iter(config['sheet_to_template'].items()))
    record = {'namak': 'lesson', 'sheet': sheet, 'template_index': template}

    class LocalSyllabus:
        warnings = []
        lookup_warnings = []

        def __init__(self):
            self.config = config

        def find(self, name):
            if normalize_key(name) == 'lesson':
                return record
            raise NotFoundError(name)

    monkeypatch.setattr(app, 'Syllabus', LocalSyllabus)
    monkeypatch.setattr(app, 'discover_assets', lambda *args: {})
    monkeypatch.setattr(app, 'load_config', lambda: config)
    item = {'files': [source.name], 'namak': 'lesson', 'sheet': sheet,
            'status': 'موفق', 'status_code': 'OK', 'warnings': []}
    monkeypatch.setattr(app, 'process_job', lambda *a, **kw: deepcopy(item))
    return source, tmp_path / 'result', config, item


def test_dry_run_matches_canonical_name_and_preserves_existing_files(local_run, monkeypatch, capsys):
    source, output, config, _ = local_run
    output.mkdir()
    (output / 'REVIEW.txt').write_bytes(b'old review')
    (output / 'report.html').write_bytes(b'old report')
    before = {p.name: p.read_bytes() for p in output.iterdir()}

    def forbidden(*args, **kwargs):
        pytest.fail('dry-run must not start processing or prepare output')

    monkeypatch.setattr(app, 'process_job', forbidden)
    monkeypatch.setattr(app, 'safe_output', forbidden)
    assert app.main(['--dry-run', '--input', str(source), '--output', str(output)]) == 0
    captured = capsys.readouterr()
    assert 'lesson' in captured.out and 'MATCH' in captured.out
    assert next(iter(config['field_labels_en'].values())) in captured.out
    assert not ARABIC.search(captured.out + captured.err)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


def test_dry_run_does_not_create_a_new_output_directory(local_run, capsys):
    source, output, _, _ = local_run
    assert app.main(['--dry-run', '--input', str(source), '--output', str(output)]) == 0
    assert not output.exists()


def test_dry_run_continues_after_an_unknown_name(local_run, capsys):
    source, output, _, _ = local_run
    (source.parent / '000_unknown.pdf').write_bytes(b'not opened')
    assert app.main(['--dry-run', '--input', str(source.parent), '--output', str(output)]) == 1
    captured = capsys.readouterr()
    assert 'E101' in captured.out and 'MATCH' in captured.out
    assert not output.exists() and not ARABIC.search(captured.out + captured.err)


@pytest.mark.parametrize('status,code', [('موفق', 0), ('بازبینی', 0), ('خطا', 1)])
def test_processing_exit_codes(local_run, status, code):
    source, output, _, item = local_run
    item.update(status=status, status_code={'موفق': 'OK', 'بازبینی': 'REVIEW', 'خطا': 'BLOCKED'}[status])
    assert app.main(['--input', str(source), '--output', str(output), '--plain']) == code


def test_startup_and_output_setup_failures_return_two_without_traceback(local_run, monkeypatch, capsys):
    source, output, _, _ = local_run

    def fail(*args, **kwargs):
        raise ValueError('خطای تنظیمات')

    monkeypatch.setattr(app, 'load_config', fail)
    assert app.main(['--input', str(source), '--output', str(output)]) == 2
    captured = capsys.readouterr()
    assert 'E201' in captured.out + captured.err
    assert not ARABIC.search(captured.out + captured.err)
    assert not output.exists()


def test_missing_input_is_startup_error_two(local_run, capsys):
    source, output, _, _ = local_run
    assert app.main(['--input', str(source.with_name('missing.pdf')),
                     '--output', str(output), '--plain']) == 2


def test_no_color_forces_plain_even_when_fancy_is_requested(local_run, monkeypatch):
    source, output, _, _ = local_run
    selected = []
    original = app.TerminalUI

    class TTY(StringIO):
        def isatty(self):
            return True

    def make_ui(*args, **kwargs):
        ui = original(*args, stream=TTY(), rich_available=True, **kwargs)
        selected.append(ui.mode)
        return ui

    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.setattr(app, 'TerminalUI', make_ui)
    assert app.main(['--input', str(source), '--output', str(output),
                     '--ui', 'fancy', '--no-color']) == 0
    assert selected == ['plain']


def test_version_has_no_run_side_effects(local_run, monkeypatch, capsys):
    _, output, config, _ = local_run
    monkeypatch.setattr(app, 'safe_output', lambda *args: pytest.fail('version must not create output'))
    assert app.main(['--version']) == 0
    assert config['tool_version'] in capsys.readouterr().out
    assert not output.exists()


@pytest.mark.parametrize('flag,word', [('--quiet', False), ('--verbose', True)])
def test_quiet_and_verbose_control_stage_updates(local_run, flag, word, capsys, monkeypatch):
    source, output, _, item = local_run

    def job(*args, event_bus, **kwargs):
        event_bus.emit('stage_started', file=source.name, stage='resolve')
        event_bus.emit('stage_finished', file=source.name, stage='resolve', seconds=.25, ok=True)
        return deepcopy(item)

    monkeypatch.setattr(app, 'process_job', job)
    assert app.main(['--input', str(source), '--output', str(output), '--plain', flag]) == 0
    text = capsys.readouterr().out
    assert ('Stage Resolve' in text) == word
    assert 'Summary:' in text and not ARABIC.search(text)


@pytest.mark.parametrize('opened', [True, False])
def test_open_report_uses_current_html_uri_without_affecting_result(local_run, monkeypatch, capsys, opened):
    import webbrowser
    source, output, _, _ = local_run
    calls = []
    monkeypatch.setattr(webbrowser, 'open', lambda uri: calls.append(uri) or opened)
    assert app.main(['--input', str(source), '--output', str(output), '--plain', '--open-report']) == 0
    assert calls == [(output / 'report.html').resolve().as_uri()]
    assert (output / 'report.html').is_file()
    assert not ARABIC.search(capsys.readouterr().out)


def test_argument_errors_remain_english_even_for_persian_user_text(capsys):
    with pytest.raises(SystemExit) as error:
        app.main(['--گزینه-نامعتبر'])
    assert error.value.code == 2
    assert not ARABIC.search(capsys.readouterr().err)


def test_doctor_reports_required_and_optional_failures_without_pdf_import_bootstrap():
    helper = Path(__file__).with_name('ui_cli_missing_dependency.py')
    result = subprocess.run([sys.executable, str(helper), 'pymupdf', 'doctor'], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'FAIL pymupdf' in result.stdout and 'Python' in result.stdout
    assert 'Traceback' not in result.stderr and not ARABIC.search(result.stdout + result.stderr)


def test_normal_run_with_missing_dependency_has_setup_exit_two():
    helper = Path(__file__).with_name('ui_cli_missing_dependency.py')
    result = subprocess.run([sys.executable, str(helper), 'pymupdf', '--plain'], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 2
    assert 'E200' in result.stdout + result.stderr
    assert 'Traceback' not in result.stderr


def test_doctor_optional_rich_failure_does_not_block_pdf_use(monkeypatch, capsys):
    import doctor
    original = doctor.importlib.import_module

    def missing_rich(name):
        if name == 'rich':
            raise ImportError('test optional missing module')
        return original(name)

    monkeypatch.setattr(doctor.importlib, 'import_module', missing_rich)
    monkeypatch.setattr(doctor, 'find_libreoffice', lambda: None)
    assert doctor.run_doctor(ROOT, []) == 0
    captured = capsys.readouterr()
    assert 'FAIL rich' in captured.out and 'optional' in captured.out
    assert 'FAIL LibreOffice' in captured.out
    assert not ARABIC.search(captured.out + captured.err)


def test_doctor_rejects_nonunique_assets_and_an_unloadable_font(tmp_path, capsys):
    import doctor
    import yaml
    config = load_config()
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    asset_dir = tmp_path / 'assets'
    asset_dir.mkdir()
    for name in ('Syllabus.xlsx', 'First_Page_Template.pdf', 'Sarbarg.pdf',
                 'Sarbarg-copy.pdf', 'Aria-Regular.otf'):
        (asset_dir / name).write_bytes(b'invalid test asset')
    assert doctor.run_doctor(tmp_path, []) == 2
    text = capsys.readouterr().out
    assert 'FAIL asset border' in text and '2 match(es)' in text
    assert 'FAIL font' in text and not ARABIC.search(text)
    assert not list((tmp_path / 'output').iterdir())


def test_doctor_rejects_wrong_required_package_version(monkeypatch, capsys):
    import doctor
    version = doctor.metadata.version
    monkeypatch.setattr(doctor.metadata, 'version', lambda package:
                        '0.0' if package == 'pymupdf' else version(package))
    assert doctor.run_doctor(ROOT, []) == 2
    text = capsys.readouterr().out
    assert 'FAIL pymupdf' in text and 'pinned version' in text


def test_doctor_distinguishes_aria_from_arial(monkeypatch, capsys):
    import doctor
    monkeypatch.setattr(app.fitz, 'Font', lambda **kwargs: SimpleNamespace(name='Arial Regular'))
    assert doctor.run_doctor(ROOT, []) == 2
    assert 'FAIL font' in capsys.readouterr().out


def test_doctor_reports_output_write_failure(monkeypatch, capsys):
    import doctor

    def fail(*args, **kwargs):
        raise PermissionError('test output is not writable')

    monkeypatch.setattr(doctor.tempfile, 'TemporaryFile', fail)
    assert doctor.run_doctor(ROOT, []) == 2
    assert 'FAIL output' in capsys.readouterr().out


def test_dry_run_merge_and_english_subject_fallback(local_run, capsys):
    source, output, config, _ = local_run
    config['field_labels_en'] = {}
    assert app.main(['--dry-run', '--merge', str(source), '--namak', 'lesson',
                     '--output', str(output)]) == 0
    text = capsys.readouterr().out
    assert 'MATCH' in text and 'field #' in text and not output.exists()


def test_open_report_never_opens_a_stale_html_file(local_run, monkeypatch):
    import webbrowser
    source, output, _, _ = local_run
    output.mkdir()
    previous = output / 'report.html'
    previous.write_bytes(b'previous run')

    def fail(*args, **kwargs):
        raise OSError('cannot write current HTML')

    monkeypatch.setattr(app, 'write_html_report', fail)
    monkeypatch.setattr(webbrowser, 'open', lambda *a: pytest.fail('must not open stale HTML'))
    assert app.main(['--input', str(source), '--output', str(output), '--plain', '--open-report']) == 0
    assert previous.read_bytes() == b'previous run'


def test_quiet_and_verbose_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as error:
        app.main(['--quiet', '--verbose'])
    assert error.value.code == 2
    assert not ARABIC.search(capsys.readouterr().err)


@pytest.mark.parametrize('exception,code', [(PermissionError('مجوز نوشتن نیست'), 2), (KeyboardInterrupt(), 130)])
def test_report_write_failure_or_interrupt_exits_cleanly(local_run, monkeypatch, capsys, exception, code):
    source, output, _, _ = local_run

    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(app, 'write_report', fail)
    assert app.main(['--input', str(source), '--output', str(output), '--plain']) == code
    captured = capsys.readouterr()
    assert 'Traceback' not in captured.err and not ARABIC.search(captured.out + captured.err)
