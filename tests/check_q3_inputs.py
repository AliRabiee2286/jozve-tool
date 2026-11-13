"""Compare Q3 input lookup/output behavior to the pre-change temporary snapshot."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from syllabus import Syllabus
from naamak import resolve_details,to_output_name

if __name__=='__main__':
    before=json.loads((ROOT/'cache/q3_inputs_before.json').read_text(encoding='utf-8'))
    s=Syllabus(ROOT/'config.yaml');after={}
    for path in sorted((ROOT/'input').glob('*.pdf')):
        try:
            match=resolve_details(path.stem,s)
            after[path.name]={'match':match,'output':to_output_name(match['namak'],suffix=match['suffix'])}
        except (LookupError,ValueError) as exc:
            after[path.name]={'error_type':type(exc).__name__,'error':str(exc)}
    differences=[{'input':name,'before':before.get(name),'after':after.get(name)}
                 for name in sorted(before.keys()|after.keys()) if before.get(name)!=after.get(name)]
    result={'inputs':len(after),'matches':sum('match' in v for v in after.values()),
            'errors':sum('error' in v for v in after.values()),'differences':differences}
    (ROOT/'cache/q3_inputs_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(bool(differences))
