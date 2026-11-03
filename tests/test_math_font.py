"""The cover may use the configured math fallback for missing Aria glyphs."""
import hashlib
from pathlib import Path

import pymupdf as fitz

from cover import build_cover
from syllabus import Syllabus, discover_assets


ROOT=Path(__file__).resolve().parents[1]


def test_math_fallback_uses_configured_font():
    syllabus=Syllabus()
    record=syllabus.find('physics_math_13')
    values={field:record[field] for field in ('teacher','course','chapter','topic')}
    cover,report=build_cover(record['template_index'],'portrait',values)
    assets=discover_assets(syllabus.config,ROOT)
    with cover:
        hashes={hashlib.sha256(cover.extract_font(font[0])[3]).digest()
                for font in cover[0].get_fonts(full=True)}
        assert hashlib.sha256(assets['font'].read_bytes()).digest() in hashes
        assert hashlib.sha256(assets['math_font'].read_bytes()).digest() in hashes
    assert report['fields']['topic']['value']==record['topic']
