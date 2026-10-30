"""Standalone checks for the handover document, using authoring dependencies."""
from pathlib import Path
import hashlib
import json
import uuid
import zipfile
from lxml import etree
from docx import Document
import pymupdf

root = Path(__file__).resolve().parents[1]
path = root / 'output/jozve_tool_handover_fa.docx'
meta = json.loads((root / 'debug/manual/authoring.json').read_text(encoding='utf-8'))
checks = {}
with zipfile.ZipFile(path) as z:
    checks['zip_integrity'] = z.testzip() is None
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    tree = etree.fromstring(z.read('word/document.xml'))
    checks['editable_text'] = len(tree.xpath('//w:t', namespaces=ns)) > 250
    checks['no_rasterized_text'] = not tree.xpath('//w:drawing', namespaces=ns)
    checks['rtl_paragraphs'] = len(tree.xpath('//w:bidi[@w:val="1"]', namespaces=ns)) > 100
    checks['aria_run_font'] = set(tree.xpath('//w:rFonts/@w:cs', namespaces=ns)) == {meta['font_family']}
    data = bytearray(z.read('word/fonts/aria.odttf'))
    key = uuid.UUID('12429A15-1A3B-4372-A627-649DF975103E').bytes[::-1]
    for i in range(32):
        data[i] ^= key[i % 16]
    checks['embedded_font_exact'] = hashlib.sha256(data).hexdigest() == meta['font_sha256']
    checks['no_title_rules'] = not etree.fromstring(z.read('word/styles.xml')).xpath('//w:pBdr', namespaces=ns)
doc = Document(path)
checks['sixteen_sections'] = len([p for p in doc.paragraphs if p.style.name in ('Title', 'Heading 1')]) == 16
checks['no_personal_author'] = doc.core_properties.author == doc.core_properties.last_modified_by == 'jozve-tool'
with pymupdf.open(root / 'debug/manual/manual.pdf') as pdf:
    checks['sixteen_rendered_pages'] = len(pdf) == 16
checks['sixteen_page_images'] = all((root / f'debug/manual/page-{i:02}.png').is_file() for i in range(1, 17))
checks['under_git_size_limit'] = path.stat().st_size < 90 * 1024 * 1024
result = {'passed': sum(bool(x) for x in checks.values()), 'failed': sum(not x for x in checks.values()), 'checks': checks}
(root / 'debug/manual/verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
assert all(checks.values())
