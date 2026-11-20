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
the detected footer occurrences (text, font, origin). After applying the same
legacy redaction rectangles, glyph count, Unicode, font, glyph ID, and paint mode
must match exactly. Origin movement is allowed only for whitespace glyphs; each
accepted movement records the original and observed origin in the page's
`trace_whitespace_shifts` evidence. Non-whitespace origins require exact tuple
equality, without tolerance. An unmatchable target or changed body glyph raises
`حذف متن` and blocks publication. Trace inspection itself does not write PDF
objects.

## Acceptance procedure

The new synthetic tests first reproduce unchanged-widget rejection and injected
body loss published as REVIEW on `156776c`. Targeted tests explicitly override
the default `not slow` marker when slow cases are named; no full suite runs.

Customer copies are staged by `(resolved output name, SHA-256)` identity. The
two math files have the same source bytes but distinct syllabus/output names and
must both be retained. The byte-identical PRE_2 aliases share an output name and
are processed once under the canonical name. The CLI processes eight outputs;
the two aliases map back to all nine original customer paths.

The 184-page acceptance set includes all pages of the seven non-PRE2 output
identities (including every ENV_1 page); it excludes the canonical PRE_2 output
and its identical duplicate input. The broader logical customer corpus has 190
pages when that three-page alias is counted. Regression uses 22 legacy inputs
plus 8 NANO inputs, with 150-dpi RGB pixels, extracted text, raw content streams
and deterministic isolated-page bytes checked separately. Timing uses paired
old/new `remove_numbers` runs on identical already-baked ENV_1 copies; bake and
file I/O are outside that timing.

## Superseded instructions

The owner's explicit request supersedes AGENTS section 2's source-write scope,
AGENTS section 7's main/push requirement, historical TASK_PLAN R3 and WORKLOG
PDF-processing freezes, and TASK_PLAN R12's restriction on acceptance artifacts.
The current branch is retained, only the allowed paths are staged, and push is
not attempted. The skills' default root-level plan placement, preliminary spec
commit and repeated approval gates are superseded by this approved bounded task;
plans are under `cache/page_safety_step12/` and are not committed.

## Previous step-12 verification (commit `34d017e`; superseded by follow-up)

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

The step-12 postcondition rejected ENV_1 content page 44 even with its
0.001-point tolerance. A read-only reproduction on
the cached bake of the hash-identical input found 1,411 expected and observed
glyphs; one `AmuzehNewNormalPS` space (glyph ID 3, paint mode 0) moves from
`(470.883, 212.691)` to `(473.319, 212.691)` after the unchanged legacy redaction.
The two footer lines are both `44`. The follow-up requires exact non-whitespace
origins. A separate p44 diagnostic found two whitespace and three non-whitespace
origin changes, the largest non-whitespace delta being 0.000015258789 pt. The new
CLI stops earlier, on content page 2, so p44 is not a CLI result.

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

## Latest owner-approved whitespace-only origin exception

The follow-up implementation changes only no-collision trace comparison and the
page evidence record. Glyph count, text, font, glyph ID and paint mode remain
exact. Origin differences are accepted only when the character is whitespace;
each accepted movement records original and observed origins on the removed-line
item and the page-level `trace_whitespace_shifts` field. Non-whitespace origins
must be exact; no tolerance or normalization is applied.

### A. Guard cases

| Case | Result | Evidence |
|---|---|---|
| Synthetic whitespace origin shift of 0.75 pt | Accepted | Exact origins and glyph identity recorded |
| Synthetic non-whitespace origin shift of 0.000001 pt | BLOCKED | Exact origin rule; no output published |
| Intentional BODY deletion | BLOCKED | `حذف متن`; no output published |
| Legacy `42` and `Page 42` clean controls | Pass | Serialized PDF bytes equal legacy removal |
| Whitespace-only changes in current customer outputs | 0 | No accepted whitespace shift appears in complete CLI evidence |

### B. Full deduplicated customer CLI

Statuses below come solely from `cache/page_safety_step12/customer_v2_cli/report.json`.
The two math PDFs are retained as separate output identities. The PRE_2 aliases
share a hash and output identity and are represented by one CLI job.

| Original file | Canonical CLI identity | Status | First blocking content page / bake REVIEW count |
|---|---|---|---|
| `math_c_7.pdf` | `math_c_7.pdf` | REVIEW | — / 0 |
| `math_c_8.pdf` | `math_c_8.pdf` | REVIEW | — / 0 |
| `physics_math_13.pdf` | `physics_math_13.pdf` | OK | — / 0 |
| `ZAMIN_ENV_1.pdf` | `ZAMIN_ENV_1.pdf` | BLOCKED | 2 / not published |
| `ZAMIN_ENV_2.pdf` | `ZAMIN_ENV_2.pdf` | BLOCKED | 3 / not published |
| `ZAMIN_ENV_3.pdf` | `ZAMIN_ENV_3.pdf` | BLOCKED | 2 / not published |
| `ZAMIN_PRE_1.pdf` | `ZAMIN_PRE_1.pdf` | BLOCKED | 7 / not published |
| `ZAMIN_PRE_2.pdf` | `ZAMIN_PRE_2.pdf` | BLOCKED | 1 / not published |
| `ZAMIN_PRE_2 (1).pdf` | Shared `ZAMIN_PRE_2.pdf` job | BLOCKED | Same bytes/output identity |
| **Complete report** | **8 unique jobs** | **1 OK / 2 REVIEW / 5 BLOCKED** | Exit 1; 337.412 s |

### C. Customer 184-page comparison

The requested set is the seven non-PRE2 output identities: all 46 ENV_1 pages are
included. The canonical PRE_2 output and its duplicate alias are excluded from
this count: three physical pages, or six logical pages counting both input names.
The reference is the pre-step-12 output under `cache/e2e_final2/`.

| Measure | Compared and equal | Unavailable due to blocked jobs | Differences among compared pages |
|---|---:|---:|---:|
| Content pages, stream and isolated-page bytes | 48 / 184 | 136 / 184 | 0 |
| 150-dpi RGB pixels | 48 / 184 | 136 / 184 | 0 |
| Extracted page text | 48 / 184 | 136 / 184 | 0 |

The 48 compared pages are the published math_c_7, math_c_8 and physics_math_13
outputs. The 136 unavailable pages are in four BLOCKED jobs in the 184-page set;
the fifth BLOCKED job is PRE_2, outside that set. ENV_1's 46 pages
are included in the set but have no newly published PDF. The requested 184-page
comparison therefore **does not pass**. No published page differed only by
whitespace origin; there are no accepted-shift page entries in this CLI run.

The first blocked page of each source was separately compared against its cached
bake. Glyph identity and count match, but each has non-whitespace origin changes:

| File / page | Glyph count | Whitespace origin changes | Non-whitespace origin changes | Identity mismatches |
|---|---:|---:|---:|---:|
| ENV_1 / 2 | 1042 | 13 | 40 | 0 |
| ENV_1 / 44 (diagnostic only) | 1411 | 2 | 3 | 0 |
| ENV_2 / 3 | 1314 | 2 | 14 | 0 |
| ENV_3 / 2 | 641 | 23 | 107 | 0 |
| PRE_1 / 7 | 891 | 14 | 62 | 0 |
| PRE_2 / 1 | 889 | 1 | 12 | 0 |

Per-glyph origins are in `cache/page_safety_step12/whitespace_trace_diagnostic.json`.
The diagnostic scanned all 139 cached content pages of the five blocked inputs,
including all 46 ENV_1 pages, and found no whitespace-only origin changes in the
no-collision path. It did not publish PDFs and is not a substitute for the
184-page output comparison.

### D. Tests and regression

The prior 62 focused tests plus two new trace-origin cases: **64 passed**, zero
failed/errors/skipped/deselected, nine existing syllabus-fallback warnings, in
133.87 seconds. No full pytest suite ran.

The 383-page regression was not rerun, as explicitly requested. The previous full
run on commit `34d017e` checked 22 legacy inputs / 285 pages and 8 NANO inputs / 98
pages: zero differences in 150-dpi pixels, extracted text, raw streams and
isolated page bytes. This follow-up changes only trace validation and report
evidence, not redaction rectangles, PDF content operations, baking, rendering or
writing. The 383-page result is prior evidence, not a fresh run for this change.
In particular, the stricter check could change which regression files publish;
their current statuses are not verified. All 121 protected files retain their
recorded SHA-256 hashes.

### E. Superseded commands, risk, rollback, unknowns

- Not run: `python tests/run_tests.py` and `python tests/run_tests.py -m slow`;
  full pytest is prohibited.
- Not run: `git push origin main`, `git push origin lean-step6:main`, or
  `git push origin v1.1-lean`; push is prohibited.
- Not run: historical `git reset --hard origin/main` or `git switch main`; that plan's
  main-branch requirement is superseded; `qa-support` and unrelated work were preserved.
- Not rerun: `python cache/page_safety_step12/run_regression.py`,
  `python cache/page_safety_step12/run_cli.py regression`, or
  `python cache/page_safety_step12/audit_outputs.py regression`, explicitly
  excluded by the owner for this trace-only change.
- Status source: only the complete `customer_v2_cli/report.json`, never a direct
  QC audit's derived status.

Risk: exact non-whitespace origin matching blocks five existing inputs whose
glyph counts and identities match but whose non-whitespace origins move during
legacy redaction. It does not silently downgrade them to REVIEW. Rollback is a
local `git revert` of this follow-up commit; no reset or push is needed. Unknown:
ENV_1's full successful CLI timing and a complete comparison of 184 newly
published pages remain unavailable because the CLI blocks five jobs. Acceptance
is **not complete**.
