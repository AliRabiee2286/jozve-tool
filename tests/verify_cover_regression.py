"""Before/after PDF pixel proof for the approved legacy cover formula change.

Use existing pre-change pipeline PDFs only after validating their source hashes
and reproducing each cover with the exact base commit's cover module.
Artifacts stay local; no baseline or customer source is written.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main as app
from naamak import resolve_details, to_output_name
from syllabus import Syllabus, load_config

BASE = '73aa259'
ARTIFACTS = ROOT / 'debug/cover_formula_acceptance'
OUTPUT = ROOT / 'tests/.cover_formula_regression'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pixels(page, dpi):
    pix = page.get_pixmap(dpi=dpi, alpha=False)
    return {'width': pix.width, 'height': pix.height, 'channels': pix.n,
            'sha256_pixels': hashlib.sha256(pix.samples).hexdigest()}


def save(name, value):
    (ARTIFACTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def protected():
    return {p.relative_to(ROOT).as_posix(): sha(p)
            for folder in ('input', 'assets', 'samples')
            for p in (ROOT / folder).rglob('*') if p.is_file()}


def prepare():
    ARTIFACTS.mkdir(exist_ok=False)
    cfg = load_config()
    prior = json.loads((ROOT / 'debug/bake_acceptance/protected_after.json').read_text(encoding='utf-8'))
    current = protected()
    assert all(current[path] == value for path, value in prior.items()
               if path != 'tests/corpus_baseline.json')
    assert sha(ROOT / 'tests/corpus_baseline.json') == prior['tests/corpus_baseline.json']
    # Exclude processing/config drift when reusing the previous pipeline PDFs.
    for name in ('main.py', 'pages.py', 'border.py', 'qc.py', 'syllabus.py', 'naamak.py', 'config.yaml'):
        original = subprocess.check_output(['git', 'show', BASE + ':' + name], cwd=ROOT)
        assert original.replace(b'\r\n', b'\n') == (ROOT / name).read_bytes().replace(b'\r\n', b'\n'), name
    module = types.ModuleType('cover_before_formula')
    code = subprocess.check_output(['git', 'show', BASE + ':cover.py'], cwd=ROOT)
    exec(compile(code, 'cover_before_formula.py', 'exec'), module.__dict__)
    syllabus = Syllabus()
    legacy = json.loads((ROOT / 'tests/corpus_baseline.json').read_text(encoding='utf-8'))
    names = sorted(row['source'] for row in legacy['files'].values())
    nano = sorted(p.name for p in (ROOT / 'input').glob('NANO-*.pdf'))
    assert len(names) == 22 and len(nano) == 8
    assert sorted(names + nano) == sorted(p.name for p in (ROOT / 'input').glob('*.pdf'))
    rows = []
    for group, inputs in (('legacy', names), ('nano', nano)):
        previous = ROOT / ('output/bake_acceptance_' + group)
        report = json.loads((previous / 'report.json').read_text(encoding='utf-8'))
        for name in inputs:
            item = next(i for i in report['items'] if i['files'] == [name])
            match = resolve_details(name, syllabus)
            record = syllabus.find(match['namak'])
            output_name = to_output_name(match['namak'], suffix=match['suffix'])
            assert item['output'] == output_name and item['qc']['passed']
            assert item['status_code'] in ('OK', 'REVIEW')
            source = ROOT / 'input' / name
            with fitz.open(source) as raw:
                orientation = module.effective_orientation(raw[0])
                count = len(raw) + 1
            values = {key: record[key] for key in cfg['cover']['fields']}
            cover, cover_report = module.build_cover(record['template_index'], orientation, values)
            with cover, fitz.open(stream=cover.tobytes(), filetype='pdf') as fresh, fitz.open(previous / output_name) as pdf:
                assert len(pdf) == count
                assert pixels(fresh[0], 150) == pixels(pdf[0], 150), name
                assert {key: val['value'] for key, val in item['cover']['fields'].items()} == values
                rows.append({'group': group, 'source': name, 'before_pdf': (previous / output_name).relative_to(ROOT).as_posix(),
                             'output': output_name, 'status_code': item['status_code'], 'values': values,
                             'before_pdf_sha256': sha(previous / output_name),
                             'pages': [pixels(page, 150) for page in pdf]})
            print('baseline verified: ' + name, flush=True)
    save('before.json', {'base_commit': BASE, 'dpi': 150, 'sources': current,
                         'baseline_sha256': sha(ROOT / 'tests/corpus_baseline.json'), 'files': rows})


def run():
    before = json.loads((ARTIFACTS / 'before.json').read_text(encoding='utf-8'))
    assert protected() == before['sources']
    assert sha(ROOT / 'tests/corpus_baseline.json') == before['baseline_sha256']
    cfg = load_config()
    OUTPUT.mkdir(exist_ok=False)
    syllabus = Syllabus()
    items, results = [], []
    started = time.perf_counter()
    for row in before['files']:
        item = app.process_job([ROOT / 'input' / row['source']], None, syllabus, cfg, OUTPUT, set())
        items.append(item)
        save('pipeline_items.json', items)
        assert item['status_code'] == row['status_code'], item
        assert item['qc']['passed'], item
        assert {key: val['value'] for key, val in item['cover']['fields'].items()} == row['values']
        assert sha(ROOT / row['before_pdf']) == row['before_pdf_sha256']
        with fitz.open(OUTPUT / row['output']) as pdf:
            pages = [pixels(page, before['dpi']) for page in pdf]
        changed = [index + 1 for index in range(max(len(pages), len(row['pages'])))
                   if index >= len(pages) or index >= len(row['pages']) or pages[index] != row['pages'][index]]
        results.append({'source': row['source'], 'group': row['group'], 'status_code': item['status_code'],
                        'pages': len(pages), 'changed_pages': changed, 'after': pages})
        save('comparison.json', {'dpi': before['dpi'], 'files': results,
                                'seconds': time.perf_counter() - started})
        print(f"{len(results)}/30 {row['source']}: {item['status_code']}, {len(pages)} pages, changed={changed}", flush=True)
        assert not changed, row['source']
    assert protected() == before['sources']
    assert sha(ROOT / 'tests/corpus_baseline.json') == before['baseline_sha256']
    print('PASS: 30 files, zero changed pages; sources and baseline unchanged', flush=True)


def proof(source):
    from cover import build_cover, effective_orientation
    syllabus = Syllabus()
    match = resolve_details(source.name, syllabus)
    record = syllabus.find(match['namak'])
    values = {key: record[key] for key in load_config()['cover']['fields']}
    with fitz.open(source) as raw:
        orientation = effective_orientation(raw[0])
        source_pages = len(raw)
    document, report = build_cover(record['template_index'], orientation, values)
    name = match['namak'].replace(' ', '_')
    with document:
        document.save(ARTIFACTS / (name + '_cover.pdf'), garbage=4, deflate=True)
    with fitz.open(ARTIFACTS / (name + '_cover.pdf')) as pdf:
        pdf[0].get_pixmap(dpi=150).save(ARTIFACTS / (name + '_cover.png'))
        region = fitz.Rect(report['fields']['topic']['bbox'])
        pdf[0].get_pixmap(dpi=300, clip=region).save(ARTIFACTS / (name + '_topic.png'))
    assert {key: val['value'] for key, val in report['fields'].items()} == values
    save(name + '_cover.json', {'source_sha256': sha(source), 'source_pages': source_pages,
                              'record': record, 'report': report})
    print(f'PASS: {name} cover built; raw values preserved', flush=True)


def audit():
    before = json.loads((ARTIFACTS / 'before.json').read_text(encoding='utf-8'))
    comparison = json.loads((ARTIFACTS / 'comparison.json').read_text(encoding='utf-8'))
    expected = {row['source']: row for row in before['files']}
    actual = {row['source']: row for row in comparison['files']}
    assert len(expected) == len(actual) == len(comparison['files']) == 30
    assert set(expected) == set(actual)
    for source, row in actual.items():
        old = expected[source]
        assert not row['changed_pages'] and row['after'] == old['pages']
        assert row['status_code'] == old['status_code'] and row['group'] == old['group']
        assert sha(ROOT / old['before_pdf']) == old['before_pdf_sha256']
    assert protected() == before['sources']
    prior = json.loads((ROOT / 'debug/bake_acceptance/protected_after.json').read_text(encoding='utf-8'))
    assert all(before['sources'][path] == value for path, value in prior.items()
               if path != 'tests/corpus_baseline.json')
    assert sha(ROOT / 'tests/corpus_baseline.json') == before['baseline_sha256']
    summary = {'dpi': before['dpi'], 'changed_pages': 0, 'sources_unchanged': True,
               'baseline_unchanged': True, 'seconds': comparison['seconds'], 'groups': {}}
    for group, count in (('legacy', 22), ('nano', 8)):
        rows = [row for row in actual.values() if row['group'] == group]
        assert len(rows) == count
        summary['groups'][group] = {'files': len(rows), 'pages': sum(row['pages'] for row in rows),
            'counts': {code: sum(row['status_code'] == code for row in rows)
                       for code in ('OK', 'REVIEW', 'BLOCKED')}}
    save('summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'run', 'proof', 'audit'))
    parser.add_argument('--source', type=Path, help='Read-only source for the cover proof')
    args = parser.parse_args()
    if args.mode == 'proof':
        if args.source is None:
            parser.error('proof requires --source')
        proof(args.source)
    elif args.mode == 'audit':
        audit()
    else:
        prepare() if args.mode == 'prepare' else run()
