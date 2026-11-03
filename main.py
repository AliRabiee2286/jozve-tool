"""Offline Windows CLI. Publish an output only after the saved PDF passes QC."""
import argparse
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from PIL import Image
import warnings
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, Syllabus, NotFoundError, load_config, discover_assets, is_empty_value
from naamak import resolve_details, to_output_name
from cover import build_cover, effective_orientation
from pages import process_pages, _preserve_rendering_attributes, raster
from border import clean_border
from qc import check_pdf
from events import EventBus
from logging_setup import setup_logging
from report_text import write_report
from ui import TerminalUI

ROOT=Path(__file__).resolve().parent


def clear_review_artifacts(output):
    (output/'REVIEW.txt').unlink(missing_ok=True)
    review=output/'review'
    if review.is_dir():
        for image in review.glob('*.png'):
            image.unlink(missing_ok=True)


def write_review_image(pdf_path, output):
    target_dir=output/'review';target_dir.mkdir(parents=True,exist_ok=True)
    target=target_dir/(Path(pdf_path).stem+'.png')
    with fitz.open(pdf_path) as document:
        pages=[document[index] for index in range(min(len(document),4))]
        images=[Image.fromarray(raster(page,25)).convert('RGB') for page in pages]
    if not images:
        raise ValueError('PDF صفحه ندارد')
    width=max(image.width for image in images);height=max(image.height for image in images)
    canvas=Image.new('RGB',(width*2,height*2),'white')
    for index,image in enumerate(images):
        x=(index%2)*width+(width-image.width)//2
        y=(index//2)*height+(height-image.height)//2
        canvas.paste(image,(x,y))
    canvas.save(target)
    return target.relative_to(output).as_posix()


def find_soffice():
    found=shutil.which('soffice')
    if found: return found
    for key in ('ProgramFiles','ProgramFiles(x86)'):
        if os.environ.get(key):
            path=Path(os.environ[key])/'LibreOffice/program/soffice.exe'
            if path.is_file(): return str(path)
    return None


def convert_office(source, directory):
    executable=find_soffice()
    if not executable: raise RuntimeError('LibreOffice نصب نیست')
    directory.mkdir(parents=True,exist_ok=True)
    profile=(directory/'profile').resolve().as_uri()
    result=subprocess.run([executable,'-env:UserInstallation='+profile,'--headless','--convert-to','pdf',
                           '--outdir',str(directory),str(source)],capture_output=True,timeout=120,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    target=directory/(source.stem+'.pdf')
    if result.returncode or not target.is_file(): raise RuntimeError('تبدیل LibreOffice به PDF ناموفق بود')
    return target


def safe_output(path,cfg):
    path=path.resolve()
    allowed=[(ROOT/cfg['paths'][k]).resolve() for k in ('output','cache','debug')]+[(ROOT/'tests').resolve()]
    protected=[(ROOT/cfg['paths'][k]).resolve() for k in ('input','assets','samples')]
    if not any(path==p or path.is_relative_to(p) for p in allowed) or any(path==p or path.is_relative_to(p) for p in protected):
        raise ValueError('مسیر خروجی باید داخل output، cache، debug یا tests پروژه باشد')
    path.mkdir(parents=True,exist_ok=True)
    return path


@contextmanager
def _timed_stage(event_bus, stage, file_name):
    started = time.perf_counter()
    event_bus.emit('stage_started', file=file_name, stage=stage)
    try:
        yield
    except BaseException as exc:
        event_bus.emit('stage_finished', file=file_name, stage=stage,
                       seconds=round(time.perf_counter()-started, 4), ok=False,
                       error=str(exc))
        raise
    else:
        event_bus.emit('stage_finished', file=file_name, stage=stage,
                       seconds=round(time.perf_counter()-started, 4), ok=True)


def process_job(paths, namak, syllabus, cfg, output, claimed, event_bus=None):
    event_bus = event_bus or EventBus()
    file_name = ', '.join(p.name for p in paths)
    item={'files':[p.name for p in paths],'status':'خطا','status_code':'BLOCKED','warnings':[]}
    try:
        with _timed_stage(event_bus, 'resolve', file_name):
            match=resolve_details(namak or paths[0].stem,syllabus)
            canonical=match['namak']; suffix=match['suffix']
            record=syllabus.find(canonical); name=to_output_name(canonical,suffix=suffix)
        item['warnings'].extend(syllabus.lookup_warnings)
        empty=[field for field in cfg['cover']['fields'] if is_empty_value(record[field])]
        if empty:
            item['warnings'].append({'kind':'empty_cover_fields','fields':empty})
        item['output_suffix']=suffix
        item['template_index']=record['template_index']
        item.update(namak=canonical,sheet=record['sheet'],output=name)
        if name.casefold() in claimed: raise ValueError('چند ورودی در همین اجرا نام خروجی یکسان دارند؛ از --merge استفاده کنید')
        claimed.add(name.casefold())
        with tempfile.TemporaryDirectory(prefix='job_',dir=ROOT/cfg['paths']['cache']) as scratch, ExitStack() as stack:
            combined=stack.enter_context(fitz.open())
            for index,path in enumerate(paths):
                if not path.is_file(): raise FileNotFoundError('فایل ورودی پیدا نشد: '+path.name)
                pdf=path
                if path.suffix.lower()!='.pdf':
                    if path.suffix.lower() not in cfg['cli']['office_extensions']: raise ValueError('پسوند پشتیبانی نمی‌شود: '+path.suffix)
                    pdf=convert_office(path,Path(scratch)/str(index))
                with fitz.open(pdf) as source:
                    if source.needs_pass: raise ValueError('PDF رمزدار است: '+path.name)
                    if not len(source): raise ValueError('PDF صفحه ندارد: '+path.name)
                    offset=len(combined);combined.insert_pdf(source)
                    _preserve_rendering_attributes(source,combined,offset,preserve_catalog=offset==0)
            orientation=effective_orientation(combined[0])
            item.update(orientation=orientation,input_pages=len(combined),output_pages=len(combined)+1)
            values={key:record[key] for key in cfg['cover']['fields']}
            with _timed_stage(event_bus, 'cover', file_name):
                cover,cover_report=build_cover(record['template_index'],orientation,values)
            stack.enter_context(cover)
            with _timed_stage(event_bus, 'border', file_name):
                clean,_=clean_border(cache_dir=scratch)
            with _timed_stage(event_bus, 'pages', file_name):
                content,page_report=process_pages(
                    combined, clean_path=clean,
                    progress=lambda index, total: event_bus.emit(
                        'stage_progress', file=file_name, stage='pages',
                        index=index, total=total))
            stack.enter_context(content)
            item['warnings'].extend(page_report['warnings']);item['pages']=page_report['pages']
            item['cover']=cover_report
            result=stack.enter_context(fitz.open(stream=cover.tobytes(),filetype='pdf'))
            result.insert_pdf(content)
            _preserve_rendering_attributes(content,result,1,preserve_catalog=False)
            # Render the actual assembly before saving: its catalog carries the
            # cover's OutputIntents, which can alter image color interpretation.
            baseline=[]; effects=[]
            for index,page in enumerate(content):
                assembled=raster(result[index+1],cfg['pages']['diagnostic_dpi'])
                baseline.append(assembled)
                raw=raster(page,cfg['pages']['diagnostic_dpi'])
                delta=np.abs(raw.astype(np.int16)-assembled.astype(np.int16))
                effects.append({'page':index+1,'different_pixels':int(np.any(delta,axis=2).sum()),
                    'pixels_over_10':int(np.any(delta>10,axis=2).sum()),
                    'percent_over_10':float(np.any(delta>10,axis=2).mean()*100),
                    'max_channel_difference':int(delta.max())})
            item['output_intents_effect']=effects
            temporary=Path(scratch)/name
            with _timed_stage(event_bus, 'qc', file_name):
                result.save(temporary,garbage=4,deflate=True)
                quality=check_pdf(temporary,combined,record,cover_report,page_report,cover,
                                  expected_content_renders=baseline,output_suffix=suffix)
            item['qc']=quality
            if quality.get('blocking_failed'):
                item['error']='کنترل‌های بلاک‌کننده رد شد: '+', '.join(quality['blocking_failed'])
                item['status_code']='BLOCKED'
                event_bus.emit('error', file=file_name, stage='qc', code='E102',
                               message=item['error'],
                               public_message='quality control failed - check output/report.txt')
                return item
            with _timed_stage(event_bus, 'write', file_name):
                os.replace(temporary,output/name)
            item['status']='بازبینی' if quality.get('advisory_failed') else 'موفق'
            item['status_code']='REVIEW' if item['status']=='بازبینی' else 'OK'
            if item['status']=='بازبینی':
                item['review_controls']=quality['advisory_failed']
    except NotFoundError:
        item['error']='نامک در سیلابس پیدا نشد؛ نام فایل یا --namak را بررسی کنید'
        event_bus.emit('error', file=file_name, stage='resolve', code='E101',
                       message=item['error'],
                       public_message='namak not found in syllabus - check the input file name')
    except Exception as exc:
        item['warnings'].extend(getattr(syllabus,'lookup_warnings',[]))
        item['error']=str(exc)
        event_bus.emit('error', file=file_name, stage='run', code='E199',
                       message=item['error'],
                       public_message='processing failed - check output/report.txt')
    return item


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description='Offline lesson note processor')
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--merge',nargs='+',type=Path);parser.add_argument('--namak')
    parser.add_argument('--ui',choices=('auto','fancy','compat','plain'),default='auto')
    parser.add_argument('--plain',action='store_true',help='Use plain English terminal output')
    parser.add_argument('--quiet',action='store_true',help='Hide per-file terminal updates')
    args=parser.parse_args(argv)
    if args.merge and (not args.namak or args.input): parser.error('--merge requires --namak and cannot be combined with --input')
    if args.namak and not args.merge: parser.error('--namak requires --merge')
    cfg=load_config();output=safe_output(args.output or ROOT/cfg['paths']['output'],cfg)
    clear_review_artifacts(output)
    event_bus=EventBus()
    logger=setup_logging(output,event_bus=event_bus)
    ui=TerminalUI('plain' if args.plain else args.ui, quiet=args.quiet, config=cfg)
    ui.attach(event_bus)
    ui.start()
    items=[];global_warnings=[]
    run_started=time.perf_counter()
    interrupted=False
    event_bus.emit('run_started',stage='run',files=0)
    try:
        assets=discover_assets(cfg,ROOT)
        logger.record_versions()
        logger.record_assets(assets)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning);syllabus=Syllabus()
        global_warnings=syllabus.warnings
        for warning in global_warnings:
            event_bus.emit('warning',stage='resolve',kind='syllabus',message=warning,
                           public_message='syllabus configuration warning - see output/report.txt')
        (ROOT/cfg['paths']['cache']).mkdir(parents=True,exist_ok=True)
        claimed=set()
        if args.merge: jobs=[([p.resolve() for p in args.merge],args.namak)]
        else:
            input_path=(args.input or ROOT/cfg['paths']['input']).resolve()
            if not input_path.exists(): raise FileNotFoundError('مسیر ورودی پیدا نشد')
            files=[input_path] if input_path.is_file() else sorted(p for p in input_path.iterdir() if p.is_file() and
                p.suffix.lower() in ['.pdf',*cfg['cli']['office_extensions']] and not p.name.lower().startswith(cfg['cli']['ignore_prefix'].lower()))
            jobs=[([p],None) for p in files if not p.name.lower().startswith(cfg['cli']['ignore_prefix'].lower())]
        if not jobs: raise ValueError('فایل ورودی قابل پردازش وجود ندارد')
        for index,(paths,namak) in enumerate(jobs,1):
            file_name=', '.join(p.name for p in paths)
            event_bus.emit('file_started',file=file_name,index=index,total=len(jobs))
            started=time.perf_counter()
            item=process_job(paths,namak,syllabus,cfg,output,claimed,event_bus=event_bus)
            item['seconds']=round(time.perf_counter()-started,2)
            items.append(item)
            for warning in item.get('warnings',[]):
                kind=warning.get('kind','unknown')
                if warning['kind']=='empty_cover_fields':
                    message='empty syllabus values: '+', '.join(warning['fields'])
                    stage='resolve'
                elif warning['kind']=='syllabus_source_conflict':
                    message='syllabus source conflict: subject sheet takes priority'
                    stage='resolve'
                else:
                    message=f'{kind}: {warning}'
                    stage='pages'
                event_bus.emit('warning',file=file_name,stage=stage,kind=kind,message=message,
                               public_message=message)
            if item.get('status')=='بازبینی' and item.get('output'):
                try:
                    item['review_image']=write_review_image(output/item['output'],output)
                except Exception as exc:
                    warning={'kind':'review_image_error','detail':str(exc)}
                    item.setdefault('warnings',[]).append(warning)
                    event_bus.emit('warning',file=file_name,stage='write',kind=warning['kind'],
                                   message=warning['detail'])
            event_bus.emit('file_done',file=file_name,status=item['status'],
                           status_code=item.get('status_code'),seconds=item['seconds'],item=item)
    except KeyboardInterrupt:
        interrupted=True
        event_bus.emit('error',file='',stage='run',code='E130',message='اجرای کاربر متوقف شد',
                       public_message='interrupted - no partial file was published')
    except Exception as exc:
        items.append({'files':['راه‌اندازی'],'status':'خطا','error':str(exc)})
        event_bus.emit('error',file='',stage='run',code='E201',message=str(exc),
                       public_message='startup failed - check output/report.txt')
    try:
        summary=write_report(output,items,global_warnings)
        counts={'OK':sum(i['status']=='موفق' for i in items),
                'REVIEW':sum(i['status']=='بازبینی' for i in items),
                'BLOCKED':sum(i['status']=='خطا' for i in items)}
        logger.flush_warnings()
        event_bus.emit('run_finished',summary=summary,counts=counts,
                       total_seconds=time.perf_counter()-run_started,
                       interrupted=interrupted)
    finally:
        logger.close()
        ui.close()
    return 130 if interrupted else int(any(i['status']=='خطا' for i in items))


if __name__=='__main__':
    raise SystemExit(main())
