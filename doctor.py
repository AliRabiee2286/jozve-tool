"""Offline environment diagnostics that work before processing dependencies load."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib
from importlib import metadata
from io import StringIO
import os
from pathlib import Path
import shutil
import sys
import tempfile


def english(value):
    return str(value).encode('ascii', 'backslashreplace').decode('ascii')


class EnglishParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        super()._print_message(english(message) if message else message, file)


def find_libreoffice():
    found = shutil.which('soffice')
    if found:
        return found
    for key in ('ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(key):
            path = Path(os.environ[key]) / 'LibreOffice/program/soffice.exe'
            if path.is_file():
                return str(path)
    return None


def collect_checks(root):
    root = Path(root).resolve()
    checks, modules = [], {}

    def check(name, ok, message, required=True):
        checks.append({'name': name, 'ok': bool(ok), 'message': message, 'required': required})

    check('Python', sys.version_info[:2] == (3, 12),
          f'{sys.version.split()[0]} - use Python 3.12 with the pinned offline wheels')
    pins = {}
    requirements = root / 'requirements.txt'
    if requirements.is_file():
        for line in requirements.read_text(encoding='utf-8').splitlines():
            if '==' in line and not line.lstrip().startswith('#'):
                package, version = line.partition('==')[::2]
                pins[package.casefold()] = version.strip()
    for package, module in (('pymupdf', 'pymupdf'), ('openpyxl', 'openpyxl'),
                            ('pyyaml', 'yaml'), ('numpy', 'numpy'), ('Pillow', 'PIL'), ('rich', 'rich')):
        optional = package == 'rich'
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                modules[package] = importlib.import_module(module)
            version = metadata.version(package)
            expected = pins.get(package.casefold())
            ok = expected is None or version == expected
            message = f'{version}' if ok else f'{version}; use pinned version {expected}'
        except Exception:
            ok = False
            message = 'unavailable - install the pinned offline wheel with this interpreter'
        if optional:
            message += ' (optional; plain UI is available)'
        check(package, ok, message, not optional)
    config, assets = None, {}
    try:
        with (root / 'config.yaml').open(encoding='utf-8-sig') as stream:
            config = modules['pyyaml'].safe_load(stream)
        if not isinstance(config, dict):
            raise ValueError('Expected a mapping')
        check('config', True, 'config.yaml loaded')
        for role, pattern in config['asset_patterns'].items():
            found = sorted(path for path in (root / config['paths']['assets']).glob(pattern) if path.is_file())
            if len(found) == 1:
                assets[role] = found[0]
            check('asset ' + role, len(found) == 1,
                  f'{len(found)} match(es) - keep exactly one matching file in assets/')
    except Exception:
        check('config', False, 'cannot read configuration - check config.yaml and PyYAML')
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            name = modules['pymupdf'].Font(fontfile=str(assets['font'])).name
        check('font', name.casefold().replace(' ', '').replace('-', '') == 'ariaregular',
              name + ' - expected Aria Regular')
    except Exception:
        check('font', False, 'cannot load the font - check the font asset and PyMuPDF')
    available = bool(find_libreoffice())
    check('LibreOffice', available, 'available' if available else
          'not found (optional for PDF input) - install LibreOffice only for Office conversion', False)
    try:
        output = (root / config['paths']['output']).resolve()
        if output == root or not output.is_relative_to(root) or any(
                output.is_relative_to((root / config['paths'][key]).resolve())
                for key in ('input', 'assets', 'samples')):
            raise ValueError('Protected output location')
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=output) as stream:
            stream.write(b'jozve doctor write probe')
            stream.flush()
        check('output', True, 'write probe passed; no probe file retained')
    except Exception:
        check('output', False, 'not writable - check the output path and folder permissions')
    return checks


def run_doctor(root=None, argv=None):
    parser = EnglishParser(description='Check the offline Jozve environment')
    parser.parse_args([] if argv is None else argv)
    try:
        checks = collect_checks(root or Path(__file__).resolve().parent)
        for row in checks:
            status = 'OK' if row['ok'] else 'FAIL'
            optional = '' if row['required'] else ' [optional]'
            print(english(f"{status} {row['name']}{optional} - {row['message']}"))
        failed = sum(not row['ok'] and row['required'] for row in checks)
        print(f'Doctor: {failed} required check(s) failed')
        return 2 if failed else 0
    except KeyboardInterrupt:
        print('Interrupted')
        return 130
    except Exception:
        print('FAIL doctor - cannot read project setup; check configuration and permissions')
        return 2


if __name__ == '__main__':
    raise SystemExit(run_doctor(argv=sys.argv[1:]))
