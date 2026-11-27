"""Match-first filename resolution. Only NotFoundError permits a shorter candidate."""
import re
from syllabus import DEFAULT_CONFIG, NotFoundError, AmbiguousError, SchemaError, load_config, normalize_key

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
    return resolve_details(filename, syllabus)['namak']


def resolve_details(filename, syllabus):
    """Return the canonical namak and any configured descriptive suffix."""
    options = list(candidates(filename))
    for candidate in options:
        try:
            return _matched_record(syllabus.find(candidate), syllabus.config)
        except NotFoundError:
            pass
    for candidate in options:
        for word in syllabus.config.get('ignorable_suffix_words', []):
            match = re.search(r'[\s_-]+(' + re.escape(word) + r')$', candidate, re.I)
            if not match:
                continue
            try:
                return _matched_record(syllabus.find(candidate[:match.start()]),
                                       syllabus.config, suffix=word)
            except NotFoundError:
                pass
    alias_match = _resolve_kind_alias(options, syllabus)
    if alias_match is not None:
        return alias_match
    raise NotFoundError(f'No matching filename candidate: {filename!r}')


def _matched_record(record, config, *, suffix=''):
    definition = config.get('qa', {}).get('kinds', {}).get(record.get('kind'))
    if definition is not None:
        expected = '_' + normalize_key(definition['namak_suffix'])
        if not normalize_key(record['namak']).endswith(expected):
            raise SchemaError(f"KIND_SUFFIX_MISMATCH: {record['namak']!r}: {record['kind']!r}")
    return {'namak': record['namak'], 'suffix': suffix}


def _resolve_kind_alias(options, syllabus):
    """Approved terminal aliases only; never rescue a schema/ambiguity error."""
    qa = syllabus.config.get('qa', {})
    aliases = qa.get('kind_suffix_aliases', {})
    kinds = qa.get('kinds', {})
    for candidate in options:
        match = re.search(r'[\s_-]+([^\s_-]+)$', candidate)
        if not match:
            continue
        word = normalize_key(match.group(1))
        meanings = set()
        for alias, targets in aliases.items():
            if normalize_key(alias) != word:
                continue
            for target in targets if isinstance(targets, list) else [targets]:
                target_key = normalize_key(target)
                expected = [kind for kind, definition in kinds.items()
                            if normalize_key(definition['namak_suffix']) == target_key]
                if not expected:
                    raise SchemaError(f'UNKNOWN_KIND_ALIAS_TARGET: {alias!r}: {target!r}')
                meanings.update((target_key, kind) for kind in expected)
        if len(meanings) > 1:
            raise AmbiguousError(candidate, sorted(meanings))
        if not meanings:
            continue
        target, expected_kind = next(iter(meanings))
        replacement = candidate[:match.start(1)] + target
        try:
            record = syllabus.find(replacement)
        except NotFoundError:
            continue
        if record.get('kind') != expected_kind:
            continue
        return {'namak': record['namak'], 'suffix': '', 'alias_applied': True,
                'warnings': [{'kind': 'kind_suffix_alias', 'status_code': 'REVIEW',
                              'source': candidate, 'target': record['namak'],
                              'from_suffix': word, 'to_suffix': target}]}
    return None


def to_output_name(namak, config_path=DEFAULT_CONFIG, *, suffix=''):
    """Build the complete output basename, preserving internal spelling/ZWNJ."""
    if not isinstance(namak, str):
        raise TypeError('namak must be a string')
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', namak.strip())
    safe = re.sub(r'\s', '_', safe).rstrip(' .')
    if not safe or not safe.strip('_ .'):
        raise ValueError('namak has no usable filename characters')
    config = load_config(config_path)
    if suffix and suffix not in config.get('ignorable_suffix_words', []):
        raise ValueError('UNSUPPORTED_OUTPUT_SUFFIX: ' + str(suffix))
    if suffix:
        safe += '_' + suffix
    prefix, version = config['output_prefix'], config['output_version']
    for part in (prefix, version):
        if not isinstance(part, str) or not part or re.search(r'[<>:"/\\|?*\x00-\x1f]', part):
            raise ValueError('Invalid output prefix/version')
    return f'{prefix}_{safe}_{version}.pdf'
