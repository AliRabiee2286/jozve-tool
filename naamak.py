"""Match-first filename resolution. Only NotFoundError permits a shorter candidate."""
import re
from syllabus import DEFAULT_CONFIG, NotFoundError, load_config

_COPY = re.compile(r'(?:\s*\(\d+\)|_+\d+_)\s*$')
_DATE = r'(?:\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])|\d{4}_(?:0[1-9]|1[0-2])_(?:0[1-9]|[12]\d|3[01])|\d{4}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))'
_PREFIX_DATE = re.compile(r'^' + _DATE + r'[\s_-]+')
_SUFFIX_DATE = re.compile(r'[\s_-]+' + _DATE + r'$')


def candidates(filename):
    """Original, successive copy suffix removals, then date/copy combinations.

    Numeric lesson suffixes are not a removable pattern. Dates require a
    separator from the lesson name and plausible month/day ranges.
    """
    if not isinstance(filename, str):
        raise TypeError('filename must be a string basename')
    name = filename.strip()
    if name.lower().endswith('.pdf'):
        name = name[:-4].rstrip()
    if not name:
        return
    copies, seen = [], set()
    current = name
    while current and current not in seen:
        seen.add(current)
        copies.append(current)
        yield current
        current = _COPY.sub('', current).rstrip()
    pending = list(copies)
    date_candidates = set()
    while pending:
        current = pending.pop(0)
        for pattern in (_PREFIX_DATE, _SUFFIX_DATE, _COPY):
            shorter = pattern.sub('', current).strip()
            if shorter and shorter not in seen:
                seen.add(shorter)
                date_candidates.add(shorter)
                pending.append(shorter)
    yield from sorted(date_candidates, key=lambda v: (-len(v), v))


def resolve(filename, syllabus):
    """Return the exact canonical spelling from the first successful lookup."""
    for candidate in candidates(filename):
        try:
            return syllabus.find(candidate)['namak']
        except NotFoundError:
            continue
    raise NotFoundError(f'No matching filename candidate: {filename!r}')


def to_output_name(namak, config_path=DEFAULT_CONFIG):
    """Build the complete output basename, preserving internal spelling/ZWNJ."""
    if not isinstance(namak, str):
        raise TypeError('namak must be a string')
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', namak.strip())
    safe = re.sub(r'\s', '_', safe).rstrip(' .')
    if not safe or not safe.strip('_ .'):
        raise ValueError('namak has no usable filename characters')
    config = load_config(config_path)
    prefix, version = config['output_prefix'], config['output_version']
    for part in (prefix, version):
        if not isinstance(part, str) or not part or re.search(r'[<>:"/\\|?*\x00-\x1f]', part):
            raise ValueError('Invalid output prefix/version')
    return f'{prefix}_{safe}_{version}.pdf'
