# Historical inspection workbook

This directory preserves the original workbook used by `tests/data/inspection_evidence.json`.

- Source commit: `4e61cb6dd496e5044d0e60ff605920f2a38b2c7c` (`ui-step7` at Q0 start).
- Source path: taken from `assets.syllabus[0]` in the unchanged inspection evidence.
- SHA-256: `6378a0e61632f164bfec386c39c52f8d71dc3d5cb5c7faa4b0bc8747b8ad344c`.
- Bytes are copied unchanged from Git; tests verify this against the existing evidence hash.

The owner approved separating historical inspection from validation of the current workbook on 2026-11-13. Historical hash, sheet, header, merged-cell and matched-row assertions remain in place. The live workbook is still discovered uniquely through the production configuration and checked independently; its hash is compared before the inspection checks and at session teardown. Existing step-1 tests also compare live lookup results with workbook cells.

No runtime Git access, cache snapshot, new dependency, or replacement baseline is required. This fixture is historical input, not a baseline for QA rendering. Changes to the current workbook require QA validation in the later planned stages.
