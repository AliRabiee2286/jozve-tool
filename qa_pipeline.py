"""Isolated QA assembly and publication; legacy process_job stays unchanged."""
from contextlib import ExitStack, nullcontext
from pathlib import Path
import os
import tempfile
import pymupdf as fitz
from syllabus import DEFAULT_CONFIG, load_config, is_empty_value
from naamak import to_output_name
from qa_cover import build_qa_cover
from qa_pages import process_qa_pages
from pages import _preserve_rendering_attributes


def assemble_qa(source, record, config_path=DEFAULT_CONFIG, *, stage=None, progress=None):
    cfg=load_config(config_path)
    values={key:record[key] for key in cfg['qa']['cover']['fields']}
    stage = stage or (lambda name: nullcontext())
    with ExitStack() as stack:
        with stage('cover'):
            cover,cr=build_qa_cover(record['kind'],record['template_index'],values,
                input_size=(source[0].rect.width,source[0].rect.height),config_path=config_path)
        stack.enter_context(cover)
        with stage('pages'):
            content,pr=process_qa_pages(source,config_path,progress=progress)
        stack.enter_context(content)
        result=stack.enter_context(fitz.open(stream=cover.tobytes(),filetype='pdf'))
        result.insert_pdf(content)
        _preserve_rendering_attributes(content,result,1,preserve_catalog=False)
        return fitz.open(stream=result.tobytes(),filetype='pdf'),cr,pr


def process_qa_job(paths,record,match,syllabus,cfg,output,claimed,event_bus,convert_office,timed_stage):
    from qa_qc import check_qa_pdf
    name=to_output_name(record['namak'],suffix=match['suffix'])
    item={'files':[p.name for p in paths],'kind':record['kind'],'namak':record['namak'],
          'sheet':record['sheet'],'output':name,'output_suffix':match['suffix'],
          'status':'خطا','status_code':'BLOCKED','warnings':list(syllabus.lookup_warnings)+match.get('warnings',[])}
    empty=[key for key in cfg['qa']['cover']['fields'] if is_empty_value(record[key])]
    if empty:item['warnings'].append({'kind':'empty_cover_fields','fields':empty})
    file_name=', '.join(item['files'])
    stage=lambda name: timed_stage(event_bus,name,file_name)
    try:
        if name.casefold() in claimed:raise ValueError('چند ورودی نام خروجی یکسان دارند؛ از --merge استفاده کنید')
        claimed.add(name.casefold())
        with tempfile.TemporaryDirectory(prefix='qa_job_',dir=DEFAULT_CONFIG.parent/cfg['paths']['cache']) as scratch, ExitStack() as stack:
            source=stack.enter_context(fitz.open())
            for index,path in enumerate(paths):
                if not path.is_file():raise FileNotFoundError(path.name)
                if path.suffix.lower() not in ['.pdf',*cfg['cli']['office_extensions']]:raise ValueError('پسوند پشتیبانی نمی‌شود')
                pdf=path if path.suffix.lower()=='.pdf' else convert_office(path,Path(scratch)/str(index))
                with fitz.open(pdf) as part:
                    if part.needs_pass or not len(part):raise ValueError('PDF رمزدار یا بدون صفحه است')
                    offset=len(source);source.insert_pdf(part)
                    _preserve_rendering_attributes(part,source,offset,preserve_catalog=offset==0)
            item.update(orientation='portrait' if source[0].rect.width<source[0].rect.height else 'landscape',
                        input_pages=len(source),output_pages=len(source)+1,template_index=record['template_index'])
            result,cr,pr=assemble_qa(source,record,stage=stage,
                progress=lambda index,total: event_bus.emit('stage_progress',file=file_name,stage='pages',index=index,total=total))
            stack.enter_context(result)
            item.update(cover=cr,pages=pr['pages']);item['warnings'].extend(pr['warnings'])
            temporary=Path(scratch)/name;result.save(temporary,garbage=4,deflate=True)
            with stage('qc'):
                quality=check_qa_pdf(temporary,source,record,cr,pr,output_suffix=match['suffix'])
                item['qc']=quality
                if not quality['passed']:raise ValueError('کنترل کیفیت QA رد شد: '+', '.join(quality['blocking_failed']))
            with stage('write'):
                os.replace(temporary,output/name)
            review=bool(quality['advisory_failed'] or match.get('alias_applied'))
            item.update(status='بازبینی' if review else 'موفق',status_code='REVIEW' if review else 'OK')
            if review:item['review_controls']=quality['advisory_failed']
    except Exception as exc:
        item['error']=str(exc)
        event_bus.emit('error',file=', '.join(item['files']),stage='run',code='E199',
                       message=str(exc),public_message='QA processing failed - check output/report.txt')
    return item
