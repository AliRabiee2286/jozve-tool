# Widget compatibility and footer glyph postcondition

## Owner-approved scope (2026-11-20)

Only `pages.py`, focused tests, and documentation may be committed. No push,
full pytest run, configuration/baseline update, or customer-file edit is allowed.
Final customer statuses must come from the complete CLI `report.json`, including
bake review pages, never from the direct-QC audit's derived status.

An unchanged widget is no longer a bake failure by itself. Widget count changes
still fail `structure_changed`, and widget pages remain ineligible for structural
REVIEW when their raster difference exceeds the cutoff.

The no-collision footer path derives the expected glyph trace by removing only
the detected footer occurrences (text, font, origin). It applies the same legacy
redaction rectangles in the same order and then compares Unicode, font, glyph ID,
paint mode, and origins with the existing 0.001-point tolerance. An unmatchable
target or changed body glyph raises the existing `حذف متن` error, which the job
handler marks BLOCKED before PDF publication. Trace extraction does not write PDF
objects; successful outputs must retain byte equality.

## Acceptance procedure

The new synthetic tests first reproduce unchanged-widget rejection and injected
body loss published as REVIEW on `156776c`. Targeted tests explicitly override
the default `not slow` marker when slow cases are named; no full suite runs.

Customer copies are staged by `(resolved output name, SHA-256)` identity. The
two math files have the same source bytes but distinct syllabus/output names and
must both be retained. The byte-identical PRE_2 aliases share an output name and
are processed once under the canonical name. The CLI processes eight outputs;
the two aliases map back to all nine original customer paths.

The customer acceptance compares all 190 logical content pages (187 physical
pages plus the 3-page PRE_2 alias) against saved PDFs from before this step; the
184-page subset excludes the six historical damaged-footer pages. Regression
uses 22 legacy inputs plus 8 NANO inputs, with 150-dpi RGB pixels, extracted text,
raw content streams and deterministic isolated-page bytes checked separately.
Timing uses paired old/new `remove_numbers` runs on identical already-baked
ENV_1 copies; bake and file I/O are outside that timing.

## Superseded instructions

The owner's explicit request supersedes AGENTS section 2's source-write scope,
AGENTS section 7's main/push requirement, historical TASK_PLAN R3 and WORKLOG
PDF-processing freezes, and TASK_PLAN R12's restriction on acceptance artifacts.
The current branch is retained, only the allowed paths are staged, and push is
not attempted. The skills' default root-level plan placement, preliminary spec
commit and repeated approval gates are superseded by this approved bounded task;
plans are under `cache/page_safety_step12/` and are not committed.

## Verification status

Initial focused run: 49 passed, zero deselected. Complete customer CLI: 1 OK,
6 REVIEW, 1 BLOCKED, exit 1, wall time 766.529 seconds. Only ENV_1 is BLOCKED.
The seven published outputs have 141 physical content pages (144 logical pages
including the PRE_2 alias), all equal to their saved references for pixels, text,
raw streams, and isolated page bytes. Of the requested 184-page subset, 139
pages are verified; 45 are unavailable because ENV_1 has no new published PDF.
The required 1 OK / 7 REVIEW and 184-page gates are therefore not passed.
Final targeted tests: **62 passed**, zero failed/error/skipped/deselected, with
nine existing syllabus-fallback warnings (127.44 seconds). The 13 cases previously
deselected by `not slow` were explicitly enabled and passed. Complete regression
CLI: exit 0, **24 OK / 6 REVIEW / 0 BLOCKED**, 910.903 seconds. All 383 output
pages match the protected reference independently for 150-dpi RGB pixels, plain
text, raw content stream bytes, and deterministic isolated page graph bytes.
All 121 protected inputs/assets/samples/config/baselines/old-output artifacts
retain their original SHA-256. Only the two approved functions in pages.py change;
`_bake_decision` and the widget `structure_changed` check are unchanged.

Five paired ENV_1 timing measurements (alternating order) produced added times
of 2.696748, 3.483503, 1.713178, 3.616480, and 5.718032 seconds. The median paired
overhead is **3.483503 seconds**; median baseline and current times are 7.636568
and 11.220302 seconds. This measures `remove_numbers` over all 46 already-baked
pages; cloning, baking, saving, fitting, border, and QC are excluded. The helper
continues after the p44 failure only on disposable in-memory diagnostic copies,
which serialize to the same bytes as the baseline in all five pairs. It does
not imply a successful current ENV_1 CLI output or a measured whole-CLI slowdown.

### Real-input acceptance finding

The new postcondition rejects ENV_1 content page 44. A read-only reproduction on
the cached bake of the hash-identical input found 1,411 expected and observed
glyphs; one `AmuzehNewNormalPS` space (glyph ID 3, paint mode 0) moves from
`(470.883, 212.691)` to `(473.319, 212.691)` after the unchanged legacy redaction.
The two footer lines are both `44`. This is a body-origin change, even though
extracted text and glyph counts match. The strict trace comparison is retained.
No tolerance increase, whitespace exception, or changed output operator is used
to force the requested CLI counts. Such a result must be reported as an unmet
acceptance gate and committed as WIP if unresolved.

## Acceptance tables

### A: widgets

| Case | Widget count before/after | Max channel delta | Outcome |
|---|---:|---:|---|
| Unchanged form, no annotation | 1 / 1 | 0 | OK |
| Form + real highlight, controlled 6-level raster injection | 1 / 1 | 6 | BLOCKED, never REVIEW |
| Same highlight experiment without form | 0 / 0 | >5 | REVIEW, positive control |
| Injected widget deletion | 1 / 0 | Measured by test | BLOCKED; structure_changed retained |

### B: byte preservation and corpus

| Scope | Files | Pages compared | Pixel/text/raw-stream/page-byte differences | Gate |
|---|---:|---:|---|---|
| Published customer outputs (physical) | 7 | 141 | 0 / 0 / 0 / 0 | Published subset passes |
| Customer logical paths including PRE_2 alias | 8 published logical paths | 144 | 0 / 0 / 0 / 0 | Partial; ENV_1 unavailable |
| Required 184-page customer subset | 9 logical paths | 139 of 184 | 0 among compared pages; 45 unavailable | Not passed |
| Legacy regression | 22 | 285 | 0 / 0 / 0 / 0 | Passed |
| NANO regression | 8 | 98 | 0 / 0 / 0 / 0 | Passed |
| Total regression | 30 | 383 | 0 / 0 / 0 / 0 | Passed |

### C: intentional body deletion

The monkeypatched legacy redaction deletes BODY on a proven no-collision fixture.
Before the change it publishes REVIEW; after the change `process_job` returns
BLOCKED with `حذف متن`, and no output PDF is published. Both `42` and `Page 42`
clean controls serialize to exactly the same bytes as legacy removal.

### D: timing, seconds

| Pair | Baseline | Current diagnostic | Added |
|---|---:|---:|---:|
| 1 | 8.195857 | 10.892606 | 2.696748 |
| 2 | 7.272715 | 10.756218 | 3.483503 |
| 3 | 9.768101 | 11.481279 | 1.713178 |
| 4 | 7.603821 | 11.220302 | 3.616480 |
| 5 | 7.636568 | 13.354600 | 5.718032 |

### E: complete customer CLI statuses

| Original path | CLI identity | Status | Published bake REVIEW pages |
|---|---|---|---:|
| math_c_7.pdf | math_c_7.pdf | REVIEW | 0 |
| math_c_8.pdf | math_c_8.pdf | REVIEW | 0 |
| physics_math_13.pdf | physics_math_13.pdf | OK | 0 |
| ZAMIN_ENV_1.pdf | ZAMIN_ENV_1.pdf | BLOCKED: p44 glyph origin | Unavailable |
| ZAMIN_ENV_2.pdf | ZAMIN_ENV_2.pdf | REVIEW | 22 |
| ZAMIN_ENV_3.pdf | ZAMIN_ENV_3.pdf | REVIEW | 25 |
| ZAMIN_PRE_1.pdf | ZAMIN_PRE_1.pdf | REVIEW | 2 |
| ZAMIN_PRE_2.pdf | ZAMIN_PRE_2.pdf | REVIEW | 3 |
| ZAMIN_PRE_2 (1).pdf | ZAMIN_PRE_2.pdf (same bytes/output; no extra CLI job) | Shared REVIEW result | Shared 3 |

## Artifacts and limits

All evidence lives below `cache/page_safety_step12/`, excluded from the commit:
`customer_cli/report.json`, `customer_comparison.json`,
`regression_cli/report.json`, `regression_comparison.json`, `timing.json`,
`widget_experiment.json`, `trace_rejection_ENV1_p44.json`, `tests_final.xml`, and
`final_verification.json`. There are no new visual-debug crops for this step;
the defect is a traced space-origin change and the PDF output is intentionally
not published. Existing `debug/footer_redaction_fix/` images predate this guard.

The initial new-test run intercepted unrelated border redaction because its
injection assumed every page contained BODY. That fixture error was corrected;
the corrected pre-change test then reproduced REVIEW instead of BLOCKED. No
acceptance result relies on the discarded initial injection failure. Customer
CLI and its acceptance audit exited 1 because the real p44 guard failed; those
are retained failures, not discarded environment errors. No full pytest, push,
baseline acceptance, blanket git staging, history reset, or acceptance relaxation
was used. The old WORKLOG full-suite commands (`python tests/run_tests.py` and
`python tests/run_tests.py -m slow`) and AGENTS `git push origin main` are not run.

Risk: the exact glyph-origin policy blocks an existing PDF whose space origin is
shifted by legacy redaction, although its text and glyph counts stay equal. The
requested customer release counts and 184-page publication gate remain unmet.
The whole-CLI successful ENV_1 overhead is unknown because the guarded run is
BLOCKED; the measured incremental guard overhead has the limited scope above.
Returning this case to REVIEW/OK requires an explicit policy decision or a
redaction change that could alter the currently byte-identical legacy result.
Rollback is a local `git revert` of this step's WIP commit; no reset or push is
needed, and no rollback has been executed. Overall acceptance is **not complete**.
