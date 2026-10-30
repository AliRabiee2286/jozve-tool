"""Render the manual with an isolated hidden Word instance for visual QA."""
from pathlib import Path
import ctypes
import json
import pymupdf
import win32com.client
import yaml

root = Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((root / 'config.yaml').read_text(encoding='utf-8'))
fonts = list((root / cfg['paths']['assets']).glob(cfg['asset_patterns']['font']))
assert len(fonts) == 1
font_path = str(fonts[0])
out = root / 'debug/manual'
out.mkdir(parents=True, exist_ok=True)
added = ctypes.windll.gdi32.AddFontResourceExW(font_path, 0, 0)
word = doc = None
try:
    word = win32com.client.DispatchEx('Word.Application')
    word.Visible = False
    word.DisplayAlerts = 0
    word.AutomationSecurity = 3
    doc = word.Documents.Open(str(root / 'output/jozve_tool_handover_fa.docx'), ReadOnly=True, AddToRecentFiles=False)
    doc.Repaginate()
    doc.ExportAsFixedFormat(str(out / 'manual.pdf'), 17)
finally:
    if doc is not None:
        doc.Close(0)
    if word is not None:
        word.Quit(0)
    if added:
        ctypes.windll.gdi32.RemoveFontResourceExW(font_path, 0, 0)
with pymupdf.open(out / 'manual.pdf') as pdf:
    info = {'pages': len(pdf), 'fonts': sorted({f[3] for p in pdf for f in p.get_fonts()})}
    for i, page in enumerate(pdf):
        page.get_pixmap(dpi=110).save(out / f'page-{i+1:02}.png')
    (out / 'render.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    print(info)
