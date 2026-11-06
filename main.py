"""Offline Windows CLI. Publish an output only after the saved PDF passes QC."""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
import warnings
from doctor import EnglishParser, english, run_doctor

ROOT=Path(__file__).resolve().parent

if __name__ == '__main__' and sys.argv[1:2] == ['doctor']:
    raise SystemExit(run_doctor(ROOT, sys.argv[2:]))

try:
    from PIL import Image
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
    from report_html import write_html_report
    from ui import TerminalUI
except Exception:
    if __name__ != '__main__':
        raise
    print('E200  required package unavailable - run python main.py doctor', file=sys.stderr)
    raise SystemExit(2)


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


def _jobs(args, cfg):
    if args.merge:
        return [([path.resolve() for path in args.merge], args.namak)]
    input_path=(args.input or ROOT/cfg['paths']['input']).resolve()
    if not input_path.exists(): raise FileNotFoundError('مسیر ورودی پیدا نشد')
    files=[input_path] if input_path.is_file() else sorted(path for path in input_path.iterdir() if path.is_file() and
        path.suffix.lower() in ['.pdf',*cfg['cli']['office_extensions']] and not path.name.lower().startswith(cfg['cli']['ignore_prefix'].lower()))
    jobs=[([path],None) for path in files if not path.name.lower().startswith(cfg['cli']['ignore_prefix'].lower())]
    if not jobs: raise ValueError('فایل ورودی قابل پردازش وجود ندارد')
    return jobs


def _dry_run(args, cfg):
    try:
        jobs=_jobs(args,cfg)
        discover_assets(cfg,ROOT)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning);syllabus=Syllabus()
        blocked=0
        print('Dry run: filename/syllabus mapping only; no PDFs or reports will be created')
        for paths,namak in jobs:
            files=', '.join(path.name for path in paths)
            try:
                match=resolve_details(namak or paths[0].stem,syllabus)
                record=syllabus.find(match['namak'])
                field=cfg.get('field_labels_en',{}).get(record['sheet'],f"field #{record['template_index']}")
                print(english(f"MATCH | {files} | {match['namak']} | {field}"))
            except NotFoundError:
                blocked+=1
                print(english(f'E101  {files}: namak not found in syllabus - check the input file name'))
            except Exception:
                blocked+=1
                print(english(f'E199  {files}: mapping failed - check the syllabus record'))
        return int(bool(blocked))
    except KeyboardInterrupt:
        print('Interrupted')
        return 130
    except Exception:
        print('E201  dry-run startup failed - check configuration, assets and input path')
        return 2


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    argv=sys.argv[1:] if argv is None else argv
    if argv[:1] == ['doctor']:
        return run_doctor(ROOT,argv[1:])
    parser=EnglishParser(description='Offline lesson note processor',epilog='Diagnostics: python main.py doctor')
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--merge',nargs='+',type=Path);parser.add_argument('--namak')
    parser.add_argument('--ui',choices=('auto','fancy','compat','plain'),default='auto')
    parser.add_argument('--plain',action='store_true',help='Use plain English terminal output')
    verbosity=parser.add_mutually_exclusive_group()
    verbosity.add_argument('--quiet',action='store_true',help='Hide per-file terminal updates')
    verbosity.add_argument('--verbose',action='store_true',help='Show stage timing updates in plain/compat mode')
    parser.add_argument('--no-color',action='store_true',help='Disable color and use plain output')
    parser.add_argument('--open-report',action='store_true',help='Open the current HTML report after processing')
    parser.add_argument('--dry-run',action='store_true',help='List filename/syllabus matches without writing output')
    parser.add_argument('--version',action='store_true',help='Print the configured tool version and exit')
    thumbnails=parser.add_mutually_exclusive_group()
    thumbnails.add_argument('--thumbs',choices=('review','all'),default='review',
                            help='Include HTML thumbnails for REVIEW files or all published files')
    thumbnails.add_argument('--no-thumbs',dest='thumbs',action='store_const',const='none',
                            help='Do not render any HTML thumbnails')
    args=parser.parse_args(argv)
    if args.merge and (not args.namak or args.input): parser.error('--merge requires --namak and cannot be combined with --input')
    if args.namak and not args.merge: parser.error('--namak requires --merge')
    try:
        cfg=load_config()
        if args.version:
            print(english('jozve-tool '+cfg['tool_version']))
            return 0
        if args.dry_run:
            return _dry_run(args,cfg)
        output=safe_output(args.output or ROOT/cfg['paths']['output'],cfg)
        clear_review_artifacts(output)
        event_bus=EventBus()
        logger=setup_logging(output,event_bus=event_bus)
    except KeyboardInterrupt:
        print('Interrupted')
        return 130
    except Exception:
        print('E201  startup failed - check configuration and output permissions',file=sys.stderr)
        return 2
    report_display_path=(output.relative_to(ROOT)/'report.html').as_posix().replace('/','\\')
    ui=TerminalUI('plain' if args.plain else args.ui, quiet=args.quiet, verbose=args.verbose,
                  no_color=args.no_color,config=cfg,report_path=report_display_path)
    ui.attach(event_bus)
    ui.start()
    items=[];global_warnings=[]
    run_started=time.perf_counter()
    interrupted=False;startup_failed=False;report_path=None;run_finished_emitted=False
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
        jobs=_jobs(args,cfg)
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
        startup_failed=True
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
                       interrupted=interrupted,report_available=False)
        run_finished_emitted=True
        try:
            report_path=write_html_report(output,items,global_warnings,thumbs=args.thumbs,config=cfg,
                                          elapsed=time.perf_counter()-run_started,interrupted=interrupted)
        except Exception as exc:
            logger.error('ساخت گزارش HTML ناموفق بود: '+str(exc),stage='report')
            event_bus.emit('warning',stage='report',kind='html_report_error',
                           message='ساخت گزارش HTML ناموفق بود',
                           public_message='HTML report unavailable - see log.txt')
        if report_path is not None:
            ui.set_report_available(report_display_path)
        if args.open_report and report_path is not None:
            try:
                if not webbrowser.open(report_path.resolve().as_uri()):
                    raise OSError('Browser did not accept the report')
            except Exception:
                logger.warning('بازکردن گزارش در مرورگر ناموفق بود',stage='report')
                event_bus.emit('warning',stage='report',public_message='Cannot open report - open report.html manually')
    except KeyboardInterrupt:
        event_bus.emit('error',stage='report',code='E130',message='ثبت گزارش متوقف شد',
                       public_message='Interrupted - report writing stopped')
        counts={'OK':sum(i['status']=='موفق' for i in items),
                'REVIEW':sum(i['status']=='بازبینی' for i in items),
                'BLOCKED':sum(i['status']=='خطا' for i in items)}
        if not run_finished_emitted:
            event_bus.emit('run_finished',summary='Interrupted',counts=counts,
                           total_seconds=time.perf_counter()-run_started,
                           interrupted=True,report_available=False)
        return 130
    except Exception as exc:
        logger.error('ثبت گزارش ناموفق بود: '+str(exc),stage='report')
        event_bus.emit('error',stage='report',code='E202',message=str(exc),
                       public_message='report writing failed - check output permissions')
        return 2
    finally:
        logger.close()
        ui.close()
    return 130 if interrupted else 2 if startup_failed else int(any(i['status']=='خطا' for i in items))


# Optional startup splash: the silhouette comes from the supplied Balatar logo.
_SPLASH_MASK = (
    '..............##..............', '.............####.............',
    '............######............', '...........########...........',
    '..........####..####..........', '.........####....####.........',
    '........####......####........', '........###........###........',
    '.......###..........###.......', '......####..........####......',
    '......###............###......', '.....###..............###.....',
    '.....###..............###.....', '....###................###....',
    '....###................###....', '...###..................###...',
    '...###.......####.......###...', '...##......########......##...',
    '..###....############....###..', '..###...######..######...###..',
    '..##...####........####...##..', '.###...###..........###...###.',
    '.###..###............###..###.', '.###..###............###..###.',
    '.##..###..............###..##.', '###..###......##......###..###',
    '###..###.....####.....###..###', '###..###....######....###..###',
    '###..###...########...###..###', '###..##...####..####..###..###',
    '###.....#####....####.###..###', '###...######......###.###..###',
    '###.######............####.###', '#########............#########',
    '##########..........##########', '####...####........####...####',
    '#.......####......####.......#', '.........############.........',
    '..........##########..........', '............######............',
)


def _show_startup_splash(argv, stream=None, environ=None):
    """Show a short truecolor animation only in an interactive modern terminal."""
    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    if any(arg in argv for arg in ('--quiet', '--plain', '--no-color', '--dry-run',
                                  '--version', '--help', '-h')) or 'NO_COLOR' in environ:
        return
    for index, arg in enumerate(argv):
        if arg in ('--ui=plain', '--ui=compat') or (
                arg == '--ui' and index + 1 < len(argv) and argv[index + 1] in ('plain', 'compat')):
            return
    try:
        from ui import _modern_terminal, _rich_modules
        if not stream.isatty() or not _modern_terminal(environ) or _rich_modules() is None:
            return
        size = shutil.get_terminal_size((80, 24))
        if size.lines < 24 or size.columns < 36:
            return
        '▀▄█'.encode(stream.encoding or 'utf-8')
    except (AttributeError, LookupError, OSError, UnicodeError):
        return
    # Keep the supplied mark's aspect ratio and derive every final frame from
    # its alpha channel; the built-in mask is only a safe rendering fallback.
    # Leave room for flight, label, and a blank last terminal row.
    height = min(40, (size.lines - 11) * 2)
    height -= height % 2
    width = min(size.columns - 8, round(height * 0.88))
    mask = _SPLASH_MASK
    try:
        from base64 import b64decode
        from io import BytesIO
        from report_html import _BALATAR_LOGO_PNG
        with Image.open(BytesIO(b64decode(_BALATAR_LOGO_PNG))) as image:
            alpha = image.getchannel('A').resize((width, height), Image.Resampling.LANCZOS)
            mask = tuple(''.join('#' if alpha.getpixel((x, y)) > 90 else '.'
                                 for x in range(width)) for y in range(height))
    except Exception:
        # Resize the conservative embedded silhouette if the image asset is absent.
        source_height = len(mask)
        source_width = len(mask[0])
        mask = tuple(''.join(
            '#' if mask[min(source_height - 1, round(y * (source_height - 1) / max(1, height - 1)))][
                min(source_width - 1, round(x * (source_width - 1) / max(1, width - 1)))] == '#'
            else '.' for x in range(width)) for y in range(height))

    rows_high = height // 2
    final_top = max(1, (size.lines - rows_high - 3) // 2 - max(1, size.lines // 12))
    travel_pixels = min(12, max(8, (size.lines - rows_high - 3) * 2))
    final_pixel = final_top * 2
    start_pixel = final_pixel + travel_pixels
    columns = size.columns - 1
    background = (8, 13, 29)
    bg_sgr = f'\x1b[48;2;{background[0]};{background[1]};{background[2]}m'
    reset = '\x1b[0m'

    def _rgb(x, y, shine=0.0, dim=1.0):
        xratio = x / max(1, width - 1)
        yratio = y / max(1, height - 1)
        blend = 0.42 * xratio + 0.58 * yratio
        color = (77 + 78 * blend, 124 - 32 * blend, 255)
        light = max(0.0, min(1.0, shine)) * 0.48
        return tuple(max(16, min(255, int((channel + (255 - channel) * light) * dim)))
                     for channel in color)

    def _put(canvas, x, y, glyph, color, lower_color=None):
        if 0 <= x < columns and 0 <= y < size.lines - 1:
            r, g, b = color
            code = f'\x1b[38;2;{r};{g};{b}m'
            if lower_color is not None:
                lr, lg, lb = lower_color
                code += f'\x1b[48;2;{lr};{lg};{lb}m'
            else:
                code += bg_sgr
            canvas[y][x] = code + glyph + bg_sgr

    def _revealed(x, y, reveal):
        # Fractional coverage interpolates motion between half-cell samples.
        import math
        base = math.floor(y)
        fraction = y - base
        coverage = 0.0
        for sample, weight in ((base, 1 - fraction), (base + 1, fraction)):
            if 0 <= sample < height and mask[sample][x] == '#':
                diagonal = 0.38 * x / max(1, width - 1) + 0.62 * sample / max(1, height - 1)
                if diagonal <= reveal:
                    coverage += weight
        return coverage

    def _paint_logo(canvas, top_pixel, reveal=1.0, scan=None, dim=1.0, outline=False):
        for cell_y in range(size.lines - 1):
            source_top = cell_y * 2 - top_pixel
            source_bottom = source_top + 1
            for x in range(width):
                top_on = _revealed(x, source_top, reveal)
                bottom_on = _revealed(x, source_bottom, reveal)
                if not (top_on or bottom_on):
                    continue
                if outline:
                    source_y = round(source_top if top_on else source_bottom)
                    neighbors = ((x - 1, source_y), (x + 1, source_y),
                                 (x, source_y - 1), (x, source_y + 1))
                    if all(0 <= nx < width and 0 <= ny < height and mask[ny][nx] == '#'
                           for nx, ny in neighbors):
                        continue
                shine = 0.0
                if scan is not None:
                    source_y = source_top if top_on else source_bottom
                    diagonal = 0.38 * x / max(1, width - 1) + 0.62 * source_y / max(1, height - 1)
                    shine = max(0.0, 1.0 - abs(diagonal - scan) / 0.09)
                def covered(y, coverage):
                    color = _rgb(x, y, shine, dim)
                    return tuple(round(background[i] + (color[i] - background[i]) * coverage)
                                 for i in range(3))
                _put(canvas, x + (columns - width) // 2, cell_y, '▀',
                     covered(source_top, top_on), covered(source_bottom, bottom_on))

    def _paint_trail(canvas, top_pixel, extent, strength=1.0):
        base_row = int((top_pixel + height + 1) // 2)
        center = columns // 2
        extent = max(0, min(extent, size.lines - base_row))
        for step in range(extent):
            fade = strength * (1.0 - step / max(1, extent))
            if fade <= 0.03:
                continue
            mix = step / max(1, extent - 1)
            color = (int(210 - 130 * mix), int(220 - 110 * mix), 255)
            color = tuple(max(18, int(channel * fade)) for channel in color)
            glyph = '█' if step < 2 else '▓' if step < 4 else '▒' if step < 7 else '░'
            half_width = 1 if step < 3 else 0
            for dx in range(-half_width, half_width + 1):
                _put(canvas, center + dx, base_row + step,
                     glyph if dx == 0 else '░', color)
            if step in (2, 5, 8) and base_row + step + 1 < size.lines:
                spark_x = center + (-2 if step == 2 else 2)
                _put(canvas, spark_x, base_row + step + 1, '.', color)

    # Compact geometric lettering: five pixel rows, rendered in three cell rows.
    letters = {
        'B': ('11110','10001','11110','10001','11110'),
        'A': ('01110','10001','11111','10001','10001'),
        'L': ('10000','10000','10000','10000','11111'),
        'T': ('11111','00100','00100','00100','00100'),
        'R': ('11110','10001','11110','10100','10010'),
    }
    name_pixels = tuple('0'.join(letters[ch][row] for ch in 'BALATAR') for row in range(5))

    def _paint_warp(canvas, t):
        import math
        q = max(0.0, min(1.0, (t - 2.5) / 0.8))
        fade = max(0.0, min(1.0, (3.8 - t) / 0.5))
        if t < 1.7 or fade <= 0:
            return
        cx, cy = columns / 2, (size.lines - 2) / 2
        # Deterministic perspective rays accelerate outward from a vanishing point.
        for i in range(42):
            angle = i * 2.399963
            radius = (0.18 + ((i * 0.618034 + q * q * 1.6) % 0.82))
            length = 1 + int(15 * q * q)
            for j in range(length):
                depth = radius - j * 0.018
                x = round(cx + math.cos(angle) * depth * columns * 0.7)
                y = round(cy + math.sin(angle) * depth * (size.lines - 2) * 0.7)
                # Keep the central mark legible throughout the jump.
                if abs(x - cx) < width / 2 + 2 and abs(y - cy) < rows_high / 2 + 1:
                    continue
                light = fade * (0.20 + 0.80 * q) * (1 - j / max(1, length))
                color = tuple(round(background[k] + (v - background[k]) * light)
                              for k, v in enumerate((130, 210, 255)))
                _put(canvas, x, y, '·' if length == 1 else '▀', color)
        pulse = max(0.0, 1 - abs(t - 2.72) / 0.14)
        if pulse:
            for x in range(columns):
                light = pulse * max(0.0, 1 - abs(x - cx) / (columns / 2))
                if abs(x - cx) > width / 2 + 2:
                    _put(canvas, x, round(cy), '─', (int(140 * light), int(200 * light), int(255 * light)))

    def _show_frame(top_pixel, reveal=1.0, scan=None, ghosts=(), trail=0,
                    trail_strength=1.0, name_strength=None, science_strength=0.0):
        nonlocal frame_number
        canvas = [[' ' for _ in range(columns)] for _ in range(size.lines - 1)]
        _paint_warp(canvas, frame_number / 30.0)
        if science_strength > 0:
            tone = tuple(int(c * science_strength) for c in (48, 94, 140))
            for side in (-1, 1):
                anchor = columns // 2 + side * (width // 2 + 3)
                for dx, dy, glyph in ((0, 0, '+'), (side, 1, '.'), (side * 2, 2, '+'),
                                      (side, 3, '.'), (0, 4, '+')):
                    _put(canvas, anchor + dx, final_top + 2 + dy, glyph, tone)
        for ghost_pixel, ghost_dim in ghosts:
            _paint_logo(canvas, ghost_pixel, dim=ghost_dim, outline=True)
        if trail:
            _paint_trail(canvas, top_pixel, trail, trail_strength)
        _paint_logo(canvas, top_pixel, reveal=reveal, scan=scan)
        if name_strength is not None:
            q = max(0.0, min(1.0, name_strength))
            name_width = len(name_pixels[0])
            # A narrower terminal uses the readable text fallback.
            if columns < name_width + 2:
                label = 'BALATAR'
                for i, ch in enumerate(label):
                    _put(canvas, (columns - len(label)) // 2 + i,
                         final_top + rows_high + 1, ch, (180, 195, 255))
            else:
                origin = (columns - name_width) // 2
                for row in range(3):
                    for x in range(name_width):
                        colors = []
                        for py in (row * 2, row * 2 + 1):
                            on = py < 5 and name_pixels[py][x] == '1'
                            shine = max(0.0, 1 - abs(x / name_width - (q * 1.4 - 0.2)) / 0.15) if q < 1 else 0
                            base = (95 + int(85 * x / name_width), 160, 255)
                            colors.append(tuple(round(background[k] +
                                ((v + (255 - v) * shine) - background[k]) * q)
                                if on else background[k] for k, v in enumerate(base)))
                        _put(canvas, origin + x, final_top + rows_high + 1 + row,
                             '▀', colors[0], colors[1])
        lines = [bg_sgr + ''.join(line) + reset for line in canvas]
        stream.write('\x1b[H' + '\n'.join(lines))
        stream.flush()
        frame_number += 1
        time.sleep(max(0.0, started + frame_number / 30.0 - time.monotonic()))

    frame_number = 0
    started = time.monotonic()
    def flight_position(t):
        # Quintic trajectory: zero velocity and acceleration at both ends.
        q = max(0.0, min(1.0, (t - 2.5) / 1.2))
        eased = q * q * q * (10 + q * (-15 + 6 * q))
        return start_pixel + 2 - (start_pixel + 2 - final_pixel) * eased

    try:
        stream.write('\x1b[?25l\x1b[2J' + bg_sgr)
        for frame in range(168):
            t = frame / 30.0
            reveal = min(1.0, 0.08 + 0.92 * t / 1.7)
            top_pixel, ghosts, trail, strength = start_pixel, (), 0, 0.0
            if 2.2 <= t < 2.5:
                q = (t - 2.2) / 0.3
                top_pixel += 2 * q * q * q * (10 + q * (-15 + 6 * q))
                trail, strength = 2, q
            elif t >= 2.5:
                q = min(1.0, (t - 2.5) / 1.2)
                top_pixel = flight_position(t)
                speed = 16 * q * q * (1 - q) * (1 - q)
                ghosts = ((flight_position(t - 0.09), 0.28 * speed),
                          (flight_position(t - 0.18), 0.13 * speed)) if speed > 0.01 else ()
                trail = round(12 * speed)
                strength = min(1.0, 1.25 * speed + 0.15 * (1 - q))
            _show_frame(top_pixel, reveal=reveal, scan=t / 1.9 if t < 2.2 else None,
                        ghosts=ghosts, trail=trail, trail_strength=strength,
                        name_strength=min(1.0, (t - 3.7) / 0.9) if t >= 3.7 else None,
                        science_strength=max(0.0, 1 - t / 1.7))
    except (OSError, UnicodeError):
        pass
    finally:
        try:
            stream.write('\x1b[0m\x1b[?25h\x1b[2J\x1b[H')
            stream.flush()
        except (OSError, UnicodeError):
            pass


if __name__=='__main__':
    _show_startup_splash(sys.argv[1:])
    raise SystemExit(main())
