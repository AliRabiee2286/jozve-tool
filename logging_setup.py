"""UTF-8 Persian run logging for the command-line application."""

from datetime import datetime
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform

from events import EVENT_NAMES


_PACKAGE_DISTRIBUTIONS = {
    'pymupdf': 'PyMuPDF',
    'openpyxl': 'openpyxl',
    'pyyaml': 'PyYAML',
    'numpy': 'numpy',
    'Pillow': 'Pillow',
}


class RunLogger:
    """Write one human-readable line and one structured record per message."""

    def __init__(self, output, run_id=None):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.text_path = self.output / 'log.txt'
        self.json_path = self.output / 'log.jsonl'
        self._text = self.text_path.open('w', encoding='utf-8', newline='\n')
        self._json = self.json_path.open('w', encoding='utf-8', newline='\n')
        self._warnings = {}
        self._subscriptions = []
        self._closed = False

    @staticmethod
    def _timestamp():
        return datetime.now().astimezone().isoformat(timespec='seconds')

    @staticmethod
    def _single_line(value):
        return str(value).replace('\r', '\\r').replace('\n', '\\n')

    def log(self, level, message, file='', stage='', **extra):
        if self._closed:
            return
        level = str(level).upper()
        timestamp = self._timestamp()
        message = self._single_line(message)
        file = self._single_line(file)
        stage = self._single_line(stage)
        text = ' | '.join((timestamp, level, self.run_id, file, stage, message))
        self._text.write(text + '\n')
        record = {
            'time': timestamp,
            'level': level,
            'run_id': self.run_id,
            'file': file,
            'stage': stage,
            'message': message,
        }
        record.update(extra)
        self._json.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
        self._text.flush()
        self._json.flush()

    def info(self, message, file='', stage='', **extra):
        self.log('INFO', message, file=file, stage=stage, **extra)

    def error(self, message, file='', stage='', **extra):
        self.log('ERROR', message, file=file, stage=stage, **extra)

    def warning(self, message, file='', stage='', key=None, **extra):
        """Collect equal warnings and write one record when the run closes."""
        identity = key if key is not None else (stage, str(message))
        entry = self._warnings.setdefault(identity, {
            'message': message,
            'file': file,
            'stage': stage,
            'extra': dict(extra),
            'count': 0,
        })
        entry['count'] += 1

    def record_versions(self, versions=None):
        if versions is None:
            versions = {'python': platform.python_version()}
            for label, distribution in _PACKAGE_DISTRIBUTIONS.items():
                try:
                    versions[label] = metadata.version(distribution)
                except metadata.PackageNotFoundError:
                    versions[label] = 'unavailable'
        else:
            versions = dict(versions)
        message = 'نسخه‌ها: ' + ', '.join(f'{key}={value}'
                                          for key, value in sorted(versions.items()))
        self.info(message, stage='metadata', versions=versions)

    def record_assets(self, assets):
        for role, raw_path in sorted(assets.items()):
            path = Path(raw_path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            self.info(f'منبع {role}: {path.name}؛ SHA256 کوتاه: {digest}',
                      stage='assets', asset=role, sha256=digest)

    def handle_event(self, name, payload):
        file = payload.get('file', '')
        stage = payload.get('stage', '')
        if name == 'run_started':
            self.info('شروع اجرا', stage='run', files=payload.get('files'))
        elif name == 'file_started':
            self.info('شروع فایل', file=file, stage='file', index=payload.get('index'),
                      total=payload.get('total'))
        elif name == 'stage_started':
            self.info('شروع مرحله', file=file, stage=stage)
        elif name == 'stage_finished':
            status = 'موفق' if payload.get('ok', True) else 'خطا'
            self.info(f'پایان مرحله: {status}', file=file, stage=stage,
                      seconds=payload.get('seconds'), error=payload.get('error'))
        elif name == 'warning':
            message = payload.get('message') or payload.get('kind') or 'هشدار نامشخص'
            self.warning(message, file=file, stage=stage,
                         key=(stage, str(message)))
        elif name == 'error':
            self.error(payload.get('message', 'خطای نامشخص'), file=file, stage=stage)
        elif name == 'file_done':
            self.info('پایان فایل: ' + str(payload.get('status', 'نامعلوم')),
                      file=file, stage='file', seconds=payload.get('seconds'),
                      status_code=payload.get('status_code'))
        elif name == 'run_finished':
            self.info('پایان اجرا: ' + str(payload.get('summary', 'نامعلوم')),
                      stage='run', counts=payload.get('counts'))

    def attach(self, event_bus):
        for name in EVENT_NAMES:
            callback = lambda payload, event=name: self.handle_event(event, payload)
            event_bus.subscribe(name, callback)
            self._subscriptions.append((event_bus, name, callback))
        return self

    def _flush_warnings(self):
        for entry in self._warnings.values():
            count = entry['count']
            message = entry['message']
            if count > 1:
                message = f'{message} (تکرار: {count})'
            self.log('WARNING', message, file=entry['file'], stage=entry['stage'],
                     repeat_count=count, **entry['extra'])
        self._warnings.clear()

    def flush_warnings(self):
        self._flush_warnings()

    def close(self):
        if self._closed:
            return
        self._flush_warnings()
        for event_bus, name, callback in self._subscriptions:
            event_bus.unsubscribe(name, callback)
        self._subscriptions.clear()
        self._text.close()
        self._json.close()
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def setup_logging(output, event_bus=None, run_id=None):
    logger = RunLogger(output, run_id=run_id)
    if event_bus is not None:
        logger.attach(event_bus)
    return logger
