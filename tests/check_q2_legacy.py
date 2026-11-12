"""Compare the pre-Q2 temporary snapshot; never generate or replace the oracle."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from syllabus import Syllabus

if __name__=='__main__':
    old=json.loads((ROOT/'cache/q2_legacy_before.json').read_text(encoding='utf-8'))
    s=Syllabus(ROOT/'config.yaml');differences=[]
    for key,expected in old.items():
        try:
            record=s.find(key)
            assert record.pop('kind')=='note'
            actual={'record':record,'warnings':s.lookup_warnings}
        except (LookupError,ValueError) as exc:
            actual={'error_type':type(exc).__name__,'error':str(exc),'warnings':s.lookup_warnings}
        if actual!=expected:differences.append({'key':key,'before':expected,'after':actual})
    result={'total':len(old),'differences':differences}
    (ROOT/'cache/q2_legacy_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Legacy keys:',len(old),'differences:',len(differences))
    raise SystemExit(bool(differences))
