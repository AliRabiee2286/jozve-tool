"""Config-driven QA subject presentation; legacy labels remain unchanged."""

def subject_parts(sheet, config):
    for kind, spec in config.get('qa', {}).get('kinds', {}).items():
        suffix = spec['sheet_suffix']
        if isinstance(sheet, str) and suffix and sheet.endswith(suffix):
            return sheet[:-len(suffix)], kind
    return sheet, None


def qa_subject_label(sheet, config):
    base, kind = subject_parts(sheet, config)
    if kind is None:
        return None
    labels = config.get('field_labels_en', {})
    label = labels.get(base, labels.get('subjects', {}).get(base))
    if label is None:
        return None
    return f"{label} ({config['qa']['kinds'][kind]['title_en']})"
