# QC text reference for removed footer lines

The text-preservation QC retains `Page.get_text()` as its strict reference format. It uses ordered `dict` text lines only to locate the exact footer text and bounding box recorded in that page's `removed` evidence (0.001-point geometry tolerance), then maps that span back to the original plain-text extraction. Only the mapped footer occurrence and its newline are removed. If any reported footer cannot be mapped or matched, the check fails closed. Identical values elsewhere in the body remain in the reference.

This changes only the advisory text-preservation comparison. It does not alter the blocking-control set, page rendering checks, bake verification, or the redaction operation. `tests/test_qc_positioned_footer_text.py` covers: a body value equal to the footer number, removal of the positioned footer line, rejection after deleting a real body word, and an unmatchable footer reference. The existing QC negative tests remain enabled.

The three previous text-warning cases (ENV_1 content pages 2, 4 and 34) were rechecked: before the change the QC reference removed every occurrence of the reported digits, whereas the saved outputs only removed the footer occurrence. The new mapper removes only the text span matched by both its exact content and position. Other characters, including repeated body digits, remain in the expected `get_text()` string.

Legacy behavior noted in the acceptance evidence: `dict` and plain-text extraction can differ in their line-break and combining-mark assembly even for an unchanged input PDF. Geometry is therefore used only to map the footer span; all remaining reference characters continue to come from the original plain-text extraction and are compared without normalization.

## Scope and verification

The owner authorized this bounded QC-only step, local commits and documentation output. No config, test baseline, customer PDF, or source file was changed. Targeted QC tests are run with the surrounding PDF-processing tests; the full pytest suite is intentionally not run.

Known pre-existing environment fact: Windows `os.replace` across the cache scratch directory and the selected output volume can raise a cross-device error on QA jobs. This QC step does not modify that publication path or behavior.
