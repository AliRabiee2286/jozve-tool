"""Isolated Q8 timing witness. No production instrumentation is modified."""
import hashlib,json,platform,sys,time
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import main
from events import EventBus
from frame import QAFrame
from syllabus import Syllabus,load_config


def run():
    cfg=load_config();syllabus=Syllabus();results=[]
    output=ROOT/'tests/results/q8_benchmark';output.mkdir(parents=True,exist_ok=True)
    paths=[ROOT/'input/ai_par_2.pdf',*sorted((ROOT/'tests/data/qa').glob('*.pdf'))]
    for path in paths:
        bus=EventBus();stack=[];events=[]
        bus.subscribe('stage_started',lambda p:stack.append(p['stage']))
        def finished(p):
            assert stack.pop()==p['stage']
            events.append(dict(p))
        bus.subscribe('stage_finished',finished)
        original=QAFrame.apply
        def draw(frame,page):
            # Count actual cover/content drawing, excluding QC reference reconstruction.
            if stack and stack[-1] in ('cover','pages'):
                with main._timed_stage(bus,'frame',path.name):return original(frame,page)
            return original(frame,page)
        started=time.perf_counter()
        with patch.object(QAFrame,'apply',draw):
            item=main.process_job([path],None,syllabus,cfg,output,set(),bus)
        wall=time.perf_counter()-started
        assert item['status_code'] in ('OK','REVIEW'),item
        seconds={name:sum(e['seconds'] for e in events if e['stage']==name)
                 for name in ('resolve','cover','border','frame','pages','qc','write')}
        results.append({'source':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                        'kind':item.get('kind','note'),'status':item['status_code'],'input_pages':item['input_pages'],
                        'seconds':seconds,'wall_seconds':wall,'events':events})
    result={'python':platform.python_version(),'platform':platform.platform(),
            'packages':{name:version(name) for name in ('PyMuPDF','openpyxl','numpy')},
            'note':'One sequential run per input, existing caches retained. frame is nested QAFrame.apply time inside cover/pages; do not add it to parent times. QC reference drawing is included only in qc. border is the existing legacy preparation stage.',
            'results':results}
    dest=ROOT/'debug/qa_e2e/timings.json';dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'kind':r['kind'],'seconds':r['seconds'],'wall_seconds':r['wall_seconds']} for r in results]))

if __name__=='__main__':run()
