"""Offline Windows CLI. Publish an output only after the saved PDF passes QC."""
import argparse
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import warnings
import numpy as np
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, Syllabus, NotFoundError, load_config, discover_assets
from naamak import resolve, to_output_name
from cover import build_cover, effective_orientation
from pages import process_pages, _preserve_rendering_attributes, raster
from border import clean_border
from qc import check_pdf

ROOT=Path(__file__).resolve().parent


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


def process_job(paths, namak, syllabus, cfg, output, claimed):
    item={'files':[p.name for p in paths],'status':'خطا','warnings':[]}
    try:
        canonical=syllabus.find(namak)['namak'] if namak else resolve(paths[0].stem,syllabus)
        record=syllabus.find(canonical); name=to_output_name(canonical)
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
            cover,cover_report=build_cover(record['template_index'],orientation,values);stack.enter_context(cover)
            clean,_=clean_border(cache_dir=scratch)
            content,page_report=process_pages(combined,clean_path=clean);stack.enter_context(content)
            item['warnings']=page_report['warnings'];item['pages']=page_report['pages']
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
            result.save(temporary,garbage=4,deflate=True)
            quality=check_pdf(temporary,combined,record,cover_report,page_report,cover,expected_content_renders=baseline)
            item['qc']=quality
            if not quality['passed']: raise ValueError('کنترل کیفیت رد شد؛ خروجی جدید منتشر نشد')
            os.replace(temporary,output/name)
            item['status']='موفق'
    except NotFoundError:
        item['error']='نامک در سیلابس پیدا نشد؛ نام فایل یا --namak را بررسی کنید'
    except Exception as exc:
        item['error']=str(exc)
    return item


def write_report(output,items,global_warnings):
    lines=['گزارش پردازش جزوه‌ها','']
    lines.extend('هشدار سیلابس: '+w for w in global_warnings)
    for item in items:
        lines+=['',f"{item['status']}: {', '.join(item['files'])}"]
        for key,label in [('namak','نامک'),('sheet','رشته'),('orientation','جهت'),('input_pages','صفحات ورودی'),('output_pages','صفحات خروجی'),('output','نام خروجی'),('error','علت خطا')]:
            if key in item:
                value={'portrait':'عمودی','landscape':'افقی'}.get(item[key],item[key]) if key=='orientation' else item[key]
                lines.append(f'{label}: {value}')
        for key,passed in item.get('qc',{}).get('checks',{}).items(): lines.append(f"  {key}: {'قبول' if passed else 'رد'}")
        for detail in item.get('qc',{}).get('details',[]): lines.append(json.dumps(detail,ensure_ascii=False))
        image_warnings=[w for w in item.get('warnings',[]) if w['kind']=='image_number_unknown']
        if image_warnings:
            affected=sorted({w['page'] for w in image_warnings})
            lines.append(f'شمارهٔ تصویری نامعلوم: {len(affected)} صفحه ({", ".join(map(str,affected))})؛ '
                         'علت هشدار: تصویر کوچک در پایین صفحه؛ ماهیت تصویر نامعلوم؛ تصویر حذف نشد.')
        for warning in item.get('warnings',[]):
            if warning['kind']!='image_number_unknown': lines.append('هشدار: '+json.dumps(warning,ensure_ascii=False))
        for effect in item.get('output_intents_effect',[]):
            lines.append('اثر OutputIntents (صرفاً گزارش): '+json.dumps(effect,ensure_ascii=False))
        for page in item.get('pages',[]):
            for removed in page['removed']: lines.append(f"حذف شمارهٔ متنی صفحه {page['page']}: {removed['text']}")
        if item['status']!='موفق': lines.append('اگر خروجی قدیمی وجود دارد، نتیجهٔ این اجرا نیست و بازنویسی نشده است.')
    success=sum(i['status']=='موفق' for i in items)
    summary=f'خلاصه: {success} موفق؛ {len(items)-success} خطا؛ {len(items)} مورد'
    lines+=['',summary]
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    (output/'report.json').write_text(json.dumps({'items':items,'summary':summary},ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description='آماده‌سازی آفلاین جزوه‌ها')
    parser.add_argument('--input',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--merge',nargs='+',type=Path);parser.add_argument('--namak')
    args=parser.parse_args(argv)
    if args.merge and (not args.namak or args.input): parser.error('--merge نیازمند --namak است و با --input جمع نمی‌شود')
    if args.namak and not args.merge: parser.error('--namak فقط همراه --merge است')
    cfg=load_config();output=safe_output(args.output or ROOT/cfg['paths']['output'],cfg)
    logger=logging.getLogger('jozve');logger.setLevel(logging.INFO);logger.propagate=False
    handler=logging.FileHandler(output/'log.txt',encoding='utf-8');logger.addHandler(handler)
    items=[];global_warnings=[]
    try:
        assets=discover_assets(cfg,ROOT)
        logger.info('شروع اجرا؛ منابع یکتا: %s',', '.join(assets))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning);syllabus=Syllabus()
        global_warnings=syllabus.warnings
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
        for paths,namak in jobs:
            print('در حال پردازش: '+', '.join(p.name for p in paths),flush=True)
            item=process_job(paths,namak,syllabus,cfg,output,claimed);items.append(item)
            logger.info('%s: %s %s',item['status'],', '.join(item['files']),item.get('error',''))
    except Exception as exc:
        items.append({'files':['راه‌اندازی'],'status':'خطا','error':str(exc)})
        logger.error('خطای راه‌اندازی: %s',exc)
    finally:
        logger.removeHandler(handler);handler.close()
    print(write_report(output,items,global_warnings))
    return int(any(i['status']!='موفق' for i in items))


if __name__=='__main__':
    raise SystemExit(main())
