"""Build the stage-3 HTML sample from three real inputs, checking the render baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main as app
from report_html import write_html_report
from syllabus import discover_assets, load_config


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse', action='store_true', help='Recheck existing outputs and regenerate HTML only')
    args = parser.parse_args()
    config = load_config()
    sources = [ROOT / config['paths']['input'] / name for name in (
        'physics_thermo_8.pdf', 'physics_thermo_9.pdf', 'ADAB_SBK_14.pdf')]
    assets = discover_assets(config, ROOT)
    protected = {path: digest(path) for path in [*sources, *assets.values()]}
    output = ROOT / 'output/step3_html_preview'
    if not args.reuse:
        with tempfile.TemporaryDirectory(prefix='.ui_report_preview_', dir=ROOT / 'tests') as scratch:
            for source in sources:
                shutil.copyfile(source, Path(scratch) / source.name)
            code = app.main(['--input', scratch, '--output', str(output), '--ui', 'plain'])
        assert code == 0, 'Short corpus must not have BLOCKED files'
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert report['counts'] == {'OK': 2, 'REVIEW': 1, 'BLOCKED': 0}, report['counts']
    assert len(report['items']) == 3
    baseline = json.loads((ROOT / 'tests/corpus_baseline.json').read_text(encoding='utf-8'))
    assert baseline['dpi'] == 72
    pages = 0
    for item in report['items']:
        expected = baseline['files'][item['output']]
        assert item['status_code'] == expected['status']
        with fitz.open(output / item['output']) as document:
            assert len(document) == len(expected['pages'])
            for page, reference in zip(document, expected['pages']):
                pix = page.get_pixmap(dpi=baseline['dpi'], alpha=False)
                actual = hashlib.sha256(pix.samples).hexdigest()
                assert (pix.width, pix.height, actual) == (
                    reference['width'], reference['height'], reference['sha256']), (
                        f'CHANGED PAGE: {item["output"]} / {page.number + 1}')
                pages += 1
    assert {path: digest(path) for path in protected} == protected, 'A protected source changed'
    if args.reuse:
        warnings = [record['message'] for line in (output / 'log.jsonl').read_text(encoding='utf-8').splitlines()
                    if (record := json.loads(line)).get('level') == 'WARNING' and not record.get('file')]
        write_html_report(output, report['items'], warnings, config=config,
                          elapsed=sum(item.get('seconds', 0) for item in report['items']))
    html = (output / 'report.html').read_text(encoding='utf-8')
    assert html.count('data:image/jpeg;base64,') == 3
    preview = ROOT / 'docs/ui_preview/report.html'
    shutil.copyfile(output / 'report.html', preview)
    print(f'Short corpus: 3 files; OK=2 REVIEW=1 BLOCKED=0; {pages} pages checked; 0 changed')
    print('Input/asset hashes unchanged; 3 inline JPEG thumbnails; sample: docs/ui_preview/report.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
