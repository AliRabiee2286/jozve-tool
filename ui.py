"""Safe terminal UI with English stdout/stderr and optional Rich rendering."""

from io import StringIO
import os
from pathlib import Path
import sys
import time

from events import EVENT_NAMES


VALID_MODES = ('auto', 'fancy', 'compat', 'plain')
_STATUS = {'موفق': 'PASS', 'بازبینی': 'REVIEW', 'خطا': 'FAIL',
           'OK': 'PASS', 'REVIEW': 'REVIEW', 'BLOCKED': 'FAIL'}
_STAGE_LABELS = {
    'resolve': 'Resolve', 'cover': 'Cover', 'pages': 'Pages',
    'border': 'Border', 'qc': 'QC', 'write': 'Write', 'run': 'Run',
}


def _rich_modules():
    try:
        from rich.console import Console, Group
        from rich.live import Live
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError:
        return None
    return Console, Group, Live, Panel, Table, Text


def _is_tty(stream):
    try:
        return bool(stream.isatty())
    except (AttributeError, OSError):
        return False


def _modern_terminal(environ):
    return bool(environ.get('WT_SESSION') or environ.get('TERM_PROGRAM') or
                environ.get('COLORTERM', '').lower() == 'truecolor')


def select_mode(requested='auto', stream=None, environ=None, rich_available=None,
                no_color=False):
    """Choose a mode without making terminal capabilities a runtime dependency."""
    if requested not in VALID_MODES:
        raise ValueError(f'Unknown UI mode: {requested}')
    stream = stream or sys.stdout
    environ = os.environ if environ is None else environ
    if rich_available is None:
        rich_available = _rich_modules() is not None
    no_color = no_color or 'NO_COLOR' in environ
    tty = _is_tty(stream)
    if requested == 'plain':
        return 'plain'
    if no_color:
        return 'plain'
    if requested == 'compat':
        return 'compat'
    if requested == 'fancy':
        return 'fancy' if tty and rich_available and not no_color else 'plain'
    if not tty or not rich_available:
        return 'plain'
    return 'fancy' if _modern_terminal(environ) else 'compat'


def _ascii(value, default='-'):
    if value is None or value == '':
        return default
    return str(value).encode('ascii', 'backslashreplace').decode('ascii')


def _status(value):
    return _STATUS.get(value, 'FAIL')


def _stage(value):
    return _STAGE_LABELS.get(value, _ascii(value, 'Idle'))


def _error_line(payload):
    code = payload.get('code')
    message = payload.get('public_message')
    raw = str(payload.get('message', ''))
    if not code and 'نامک' in raw:
        code, message = 'E101', 'namak not found in syllabus - check the input file name'
    if not code:
        code, message = 'E199', message or 'processing failed - check output/report.txt'
    return f'{code}  {_ascii(message)}'


class TerminalUI:
    """Event subscriber that never raises into the PDF processing path."""

    def __init__(self, requested='auto', stream=None, quiet=False, environ=None,
                 rich_available=None, no_color=False, config=None):
        self.stream = stream or sys.stdout
        self.environ = os.environ if environ is None else environ
        self.mode = select_mode(requested, self.stream, self.environ,
                                rich_available, no_color)
        self.quiet = quiet
        self.config = config or {}
        self.files = {}
        self.current_file = ''
        self.current_stage = 'run'
        self.current_progress = (0, 0)
        self.total_files = 0
        self.started = None
        self.finished = False
        self.summary = None
        self._bus = None
        self._subscriptions = []
        self._rich = _rich_modules() if self.mode == 'fancy' else None
        self._console = None
        self._live = None

    def attach(self, event_bus):
        self._bus = event_bus
        for name in EVENT_NAMES:
            callback = lambda payload, event=name: self._safe_event(event, payload)
            event_bus.subscribe(name, callback)
            self._subscriptions.append((name, callback))
        return self

    def _safe_event(self, name, payload):
        try:
            self.handle_event(name, payload)
        except Exception:
            # UI failures must never stop processing or QC.
            return

    def start(self):
        self.started = time.perf_counter()
        if self.mode == 'fancy' and self._rich:
            try:
                Console, _, Live, _, _, _ = self._rich
                self._console = Console(file=self.stream, force_terminal=True,
                                        color_system='standard', width=110)
                if not self.quiet:
                    self._console.print('[bold cyan]JO[/bold cyan][bold blue]ZVE[/bold blue] '
                                        '[bold magenta]TOOL[/bold magenta] [dim]offline lesson processor[/dim]')
                self._live = Live(self.render(), console=self._console,
                                  refresh_per_second=12, transient=False)
                self._live.start(refresh=True)
            except Exception:
                self._console = None
                self._live = None
                self._rich = None
                self.mode = 'plain'

    def close(self):
        if self._live is not None:
            try:
                self._live.update(self.render())
                self._live.stop()
            except Exception:
                pass
            self._live = None
        if self._bus is not None:
            for name, callback in self._subscriptions:
                self._bus.unsubscribe(name, callback)
        self._subscriptions.clear()

    def _write(self, line):
        if self.mode == 'fancy' and self._live is not None:
            return
        self.stream.write(_ascii(line) + '\n')
        self.stream.flush()

    def _subject_label(self, item, index):
        labels = self.config.get('field_labels_en', {})
        sheet = item.get('sheet') if isinstance(item, dict) else None
        subjects = labels.get('subjects', {}) if isinstance(labels, dict) else {}
        return _ascii(labels.get(sheet, subjects.get(sheet, f'field #{index}')))

    def _refresh_fancy(self):
        if self._live is not None:
            self._live.update(self.render())

    def handle_event(self, name, payload):
        payload = payload or {}
        file_name = payload.get('file', '')
        if file_name:
            self.current_file = file_name
        if name == 'run_started':
            if not self.quiet and self.mode != 'fancy':
                self._write('Starting run')
        elif name == 'file_started':
            self.current_file = file_name
            self.total_files = max(self.total_files, int(payload.get('total') or 0))
            self.files.setdefault(file_name, {'stage': 'run', 'status': 'RUNNING'})
            if not self.quiet and self.mode != 'fancy':
                self._write(f"Processing: {_ascii(file_name)} ({payload.get('index', '?')}/{payload.get('total', '?')})")
        elif name == 'stage_started':
            self.current_stage = payload.get('stage', 'run')
            self.files.setdefault(file_name, {})['stage'] = self.current_stage
        elif name == 'stage_progress':
            self.current_stage = payload.get('stage', 'pages')
            self.current_progress = (payload.get('index', 0), payload.get('total', 0))
            if self.mode == 'plain' and not self.quiet:
                self._write(f'Stage {_stage(self.current_stage)}: {self.current_progress[0]}/{self.current_progress[1]}')
        elif name == 'warning':
            if self.mode != 'fancy' and not self.quiet:
                message = payload.get('public_message') or payload.get('message') or payload.get('kind', 'warning')
                suffix = '' if 'see output/report.txt' in str(message) else ' - see output/report.txt'
                self._write(f'WARN {_ascii(message)}{suffix}')
        elif name == 'error':
            self._write(_error_line(payload))
        elif name == 'file_done':
            item = payload.get('item') or {}
            status = _status(payload.get('status_code') or payload.get('status'))
            self.files[file_name] = {
                **self.files.get(file_name, {}), 'item': item, 'status': status,
                'stage': 'done', 'seconds': payload.get('seconds', item.get('seconds', 0)),
            }
            if self.mode != 'fancy' and not self.quiet:
                self._write(f"{status} {_ascii(file_name)} ({payload.get('seconds', 0)}s)")
        elif name == 'run_finished':
            self.emit_summary(payload.get('counts', {}), payload.get('total_seconds'),
                              interrupted=payload.get('interrupted', False))
        self._refresh_fancy()

    def emit_summary(self, counts, total_seconds=None, interrupted=False):
        self.summary = dict(counts or {})
        self.summary.setdefault('OK', 0)
        self.summary.setdefault('REVIEW', 0)
        self.summary.setdefault('BLOCKED', 0)
        self.finished = True
        total_seconds = total_seconds if total_seconds is not None else (
            time.perf_counter() - self.started if self.started else 0)
        if self.mode != 'fancy':
            prefix = 'Interrupted' if interrupted else 'Summary'
            self._write(f'{prefix}: OK={self.summary["OK"]} REVIEW={self.summary["REVIEW"]} '
                        f'BLOCKED={self.summary["BLOCKED"]} | Total: {total_seconds:.2f}s')
            self._write('Report: output\\report.html')
            for row in self.files.values():
                if row.get('status') == 'REVIEW' and row.get('item', {}).get('review_image'):
                    self._write('Review image: ' + _ascii(row['item']['review_image']))
        if self._live is not None:
            self._live.update(self.render())

    def render(self):
        if not self._rich:
            return ''
        _, Group, _, Panel, Table, Text = self._rich
        counts = self.summary or {'OK': 0, 'REVIEW': 0, 'BLOCKED': 0}
        elapsed = time.perf_counter() - self.started if self.started else 0
        table = Table(title='Files', expand=True)
        for column in ('Status', 'File', 'Slug', 'Subject', 'Orientation', 'Pages', 'Stage', 'Time'):
            table.add_column(column, overflow='ellipsis')
        for index, (file_name, row) in enumerate(self.files.items(), 1):
            item = row.get('item', {})
            status = row.get('status', 'RUNNING')
            style = {'PASS': 'green', 'REVIEW': 'yellow', 'FAIL': 'red'}.get(status, 'cyan')
            pages = item.get('input_pages', '-')
            if item.get('output_pages'):
                pages = f'{pages}->{item["output_pages"]}'
            table.add_row(Text(status, style=style), _ascii(file_name),
                          _ascii(item.get('namak', f'field #{index}')),
                          self._subject_label(item, index),
                          _ascii({'portrait': 'Portrait', 'landscape': 'Landscape'}.get(
                              item.get('orientation'), item.get('orientation', '-'))),
                          _ascii(pages), _stage(row.get('stage', self.current_stage)),
                          f"{row.get('seconds', 0):.2f}s")
        completed = sum(row.get('status') in ('PASS', 'REVIEW', 'FAIL') for row in self.files.values())
        total = max(len(self.files), self.total_files if hasattr(self, 'total_files') else 0)
        ratio = completed / total if total else 0
        bar = '#' * round(ratio * 20) + '-' * (20 - round(ratio * 20))
        eta = '--'
        if completed and total > completed:
            eta = f'{elapsed / completed * (total - completed):.1f}s'
        top = Text(f"Overall [{bar}] {completed}/{total}  ETA {eta}  "
                   f"OK={counts.get('OK', 0)}  REVIEW={counts.get('REVIEW', 0)}  "
                   f"BLOCKED={counts.get('BLOCKED', 0)}  {elapsed:.1f}s", style='bold')
        page = Text(f'Page progress: {self.current_progress[0]}/{self.current_progress[1]} '
                    f'({_stage(self.current_stage)})', style='dim')
        reviews = [f"Review image: {_ascii(row['item']['review_image'])}"
                   for row in self.files.values()
                   if row.get('status') == 'REVIEW' and row.get('item', {}).get('review_image')]
        summary_text = 'Report: output\\report.html' + ('\n' + '\n'.join(reviews) if reviews else '')
        summary = Panel(summary_text, title='Complete' if self.finished else 'Running')
        return Group(top, table, page, summary)


def write_ui_previews(directory):
    """Create the four small offline SVG samples requested by the UI plan."""
    modules = _rich_modules()
    if not modules:
        raise RuntimeError('rich is required to create UI previews')
    Console, _, _, Panel, Table, _ = modules
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for real in (False, True):
        for mode in ('fancy', 'compat'):
            console = Console(file=StringIO(), record=True, width=100, color_system='standard')
            title = 'Real short run' if real else 'Synthetic run'
            table = Table(title=f'{title} / {mode}')
            table.add_column('Status'); table.add_column('File'); table.add_column('Stage')
            table.add_row('PASS' if mode == 'compat' else '✓',
                          'physics_thermo_8.pdf' if real else 'example.pdf', 'QC')
            console.print(Panel(table, title='JOZVE TOOL'))
            console.print('Summary: OK=1 REVIEW=0 BLOCKED=0 | Report: output\\report.html')
            svg = console.export_svg()
            svg = svg[svg.find('<svg'):]
            path = directory / f"{'real' if real else 'fake'}_{mode}.svg"
            path.write_text(svg, encoding='utf-8')
            paths.append(path)
    return paths
