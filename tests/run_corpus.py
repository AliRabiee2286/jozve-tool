"""Run the input corpus and compare low-resolution rendered-page hashes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pymupdf as fitz


ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'config.yaml'
BASELINE=ROOT/'tests/corpus_baseline.json'
CORPUS_OUTPUT=ROOT/'output/corpus'
RENDER_DPI=72


def load_config():
    import yaml
    return yaml.safe_load(CONFIG.read_text(encoding='utf-8-sig'))


def source_files():
    config=load_config()
    input_dir=ROOT/config['paths']['input']
    extensions={'.pdf',*(suffix.lower() for suffix in config['cli']['office_extensions'])}
    ignore=config['cli']['ignore_prefix'].casefold()
    return sorted(path for path in input_dir.iterdir()
                  if path.is_file() and path.suffix.casefold() in extensions
                  and not path.name.casefold().startswith(ignore))


def render_hashes(path):
    pages=[]
    with fitz.open(path) as document:
        for number, page in enumerate(document, 1):
            pixmap=page.get_pixmap(dpi=RENDER_DPI, alpha=False)
            pages.append({'page':number, 'width':pixmap.width, 'height':pixmap.height,
                          'sha256':hashlib.sha256(pixmap.samples).hexdigest()})
    return pages


def status_code(item):
    if item.get('status')=='موفق':
        return 'OK'
    if item.get('status')=='بازبینی':
        return 'REVIEW'
    return 'BLOCKED'


def run_main(sources, selected):
    CORPUS_OUTPUT.mkdir(parents=True, exist_ok=True)
    started=time.perf_counter()
    if selected is None:
        command=[sys.executable, 'main.py', '--input', str(ROOT/'input'),
                 '--output', str(CORPUS_OUTPUT)]
        completed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,
                                 encoding='utf-8',errors='replace',timeout=3600,
                                 env={**os.environ,'PYTHONUTF8':'1'})
        report_path=CORPUS_OUTPUT/'report.json'
        if report_path.is_file():
            report=json.loads(report_path.read_text(encoding='utf-8'))
            return report.get('items',[]), time.perf_counter()-started, completed
        return [{'files':[path.name], 'status':'خطا', 'status_code':'BLOCKED',
                         'error':'گزارش اجرای corpus ساخته نشد'} for path in sources], \
            time.perf_counter()-started, completed

    items=[]
    for source in selected:
        command=[sys.executable, 'main.py', '--input', str(source),
                 '--output', str(CORPUS_OUTPUT)]
        completed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,
                                 encoding='utf-8',errors='replace',timeout=3600,
                                 env={**os.environ,'PYTHONUTF8':'1'})
        report_path=CORPUS_OUTPUT/'report.json'
        if report_path.is_file():
            report=json.loads(report_path.read_text(encoding='utf-8'))
            items.extend(report.get('items',[]))
        else:
            items.append({'files':[source.name], 'status':'خطا', 'status_code':'BLOCKED',
                           'error':'گزارش اجرای corpus ساخته نشد'})
    return items, time.perf_counter()-started, None


def snapshot(items):
    files={}
    for item in items:
        if status_code(item)=='BLOCKED' or not item.get('output'):
            continue
        output=CORPUS_OUTPUT/item['output']
        if output.is_file():
            files[item['output']]={'source':item['files'][0],
                                   'status':status_code(item),
                                   'pages':render_hashes(output)}
    return {'dpi':RENDER_DPI, 'files':files}


def compare(current, expected):
    changed=[]
    expected_files=expected.get('files',{})
    for output, current_file in current.get('files',{}).items():
        old=expected_files.get(output)
        if old is None:
            changed.append(f'{output}: فایل جدید')
            continue
        old_pages=old.get('pages',[]);new_pages=current_file.get('pages',[])
        for index in range(max(len(old_pages),len(new_pages))):
            if index>=len(old_pages) or index>=len(new_pages):
                changed.append(f'{output}: صفحه {index+1}')
            elif old_pages[index].get('sha256')!=new_pages[index].get('sha256') \
                    or old_pages[index].get('width')!=new_pages[index].get('width') \
                    or old_pages[index].get('height')!=new_pages[index].get('height'):
                changed.append(f'{output}: صفحه {index+1}')
    for output in expected_files:
        if output not in current.get('files',{}):
            changed.append(f'{output}: فایل حذف‌شده')
    return changed


def print_table(items, total_seconds):
    print('| فایل | وضعیت | صفحات | زمان (ثانیه) |')
    print('|---|---|---:|---:|')
    for item in items:
        pages='-'
        if item.get('input_pages') is not None:
            pages=f"{item.get('input_pages','-')}→{item.get('output_pages','-')}"
        seconds=item.get('seconds','-')
        print(f"| {', '.join(item.get('files',[]))} | {status_code(item)} | {pages} | {seconds} |")
    print(f'زمان کل: {total_seconds:.2f} ثانیه')


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description='Run and baseline the PDF corpus')
    parser.add_argument('--accept-baseline',action='store_true',
                        help='write tests/corpus_baseline.json after a full successful corpus run')
    parser.add_argument('--only',help='run files whose name contains this section')
    args=parser.parse_args(argv)

    sources=source_files()
    selected=None
    if args.only:
        needle=args.only.casefold()
        selected=[path for path in sources if needle in path.name.casefold()]
        if not selected:
            print(f'No corpus input matched: {args.only}')
            return 1
    if args.accept_baseline and (args.only or len(sources)!=22):
        print('Baseline can be accepted only for the full 22-file corpus.')
        return 1

    items,total,completed=run_main(sources,selected)
    print_table(items,total)
    blocked=[item for item in items if status_code(item)=='BLOCKED']
    current=snapshot(items)
    changed=[]
    if args.accept_baseline:
        if blocked or len(items)!=22 or len(current['files'])!=22:
            print('Baseline was not written: corpus has BLOCKED or missing outputs.')
            return 1
        BASELINE.write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'Baseline written: {BASELINE.relative_to(ROOT)}')
    else:
        if not BASELINE.is_file():
            print(f'Baseline missing: {BASELINE.relative_to(ROOT)}')
            return 1
        expected=json.loads(BASELINE.read_text(encoding='utf-8'))
        if expected.get('dpi')!=RENDER_DPI:
            print('Baseline DPI does not match the corpus runner.')
            return 1
        if args.only:
            needle=args.only.casefold()
            expected={'dpi':expected['dpi'], 'files':{
                output:data for output,data in expected.get('files',{}).items()
                if needle in output.casefold() or needle in data.get('source','').casefold()}}
        changed=compare(current,expected)
        if changed:
            print('صفحات تغییرکرده:')
            for page in changed:
                print('- '+page)
    if completed is not None and completed.returncode not in (0,1):
        return completed.returncode
    return 1 if blocked or changed else 0


if __name__=='__main__':
    raise SystemExit(main())
