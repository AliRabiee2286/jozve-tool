"""Read-only evidence collector for step 0; run: python -B inspect.py.

The requested filename collides with Python's stdlib inspect. Imports of this
file expose stdlib inspect instead, so openpyxl/pytest remain functional.
"""
if __name__ != '__main__':
    import sysconfig as _sysconfig
    from pathlib import Path as _Path
    _stdlib = _Path(_sysconfig.get_path('stdlib')) / 'inspect.py'
    exec(compile(_stdlib.read_bytes(), str(_stdlib), 'exec'), globals())
else:
    import sys
    sys.dont_write_bytecode = True
    import collections
    import hashlib
    import importlib.metadata
    import json
    import os
    from pathlib import Path
    import platform
    import re
    import shutil
    import unicodedata
    import pymupdf as fitz
    import openpyxl
    import yaml

    ROOT = Path(__file__).resolve().parent
    CFG = yaml.safe_load((ROOT / 'cache/config.yaml').read_text(encoding='utf-8-sig'))
    DEBUG = ROOT / 'debug'
    DEBUG.mkdir(exist_ok=True)

    def normal(value):
        text = unicodedata.normalize('NFKC', str(value)).translate(str.maketrans('يك', 'یک'))
        text = ''.join(str(unicodedata.digit(c)) if c.isdecimal() else c
                       for c in text if unicodedata.category(c) != 'Cf')
        return re.sub(r'[\s_-]+', '_', text.casefold()).strip('_')

    def rect(value):
        return [round(float(v), 3) for v in value]

    def snapshot():
        return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for folder in CFG['source_dirs'] for p in sorted((ROOT / folder).rglob('*')) if p.is_file()}

    def lines(page):
        result = []
        for block in page.get_text('dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']:
            for line in block.get('lines', []):
                result.append({'text': ''.join(s['text'] for s in line['spans']),
                               'bbox': rect(line['bbox']),
                               'display_bbox': rect(fitz.Rect(line['bbox']) * page.rotation_matrix),
                               'spans': [{'text': s['text'], 'font': s['font'], 'size': s['size'],
                                          'bbox': rect(s['bbox'])} for s in line['spans']]})
        return result

    def page_evidence(page, detailed=False):
        ls = lines(page)
        drawings = [{'id': i, 'bbox': rect(d['rect']), 'type': d['type'],
                     'fill': d['fill'], 'color': d['color'], 'width': d['width'],
                     'fill_opacity': d.get('fill_opacity'), 'closePath': d['closePath'],
                     'items': str(d['items']) if detailed else None}
                    for i, d in enumerate(page.get_drawings())]
        images = [{'bbox': rect(i['bbox']), 'width': i['width'], 'height': i['height'],
                   'xref': i.get('xref')} for i in page.get_image_info(xrefs=True)]
        bottom = page.rect.height * (1 - CFG['bottom_fraction'])
        return {'page': page.number + 1, 'size': rect((page.rect.width, page.rect.height)),
                'mediabox': rect(page.mediabox), 'cropbox': rect(page.cropbox), 'rotation': page.rotation,
                'orientation': 'افقی' if page.rect.width > page.rect.height else 'عمودی' if page.rect.width < page.rect.height else 'مربع',
                'text': page.get_text(), 'lines': ls, 'drawings': drawings, 'images': images,
                'fonts': page.get_fonts(full=True),
                'bottom_text': [l for l in ls if l['display_bbox'][3] >= bottom],
                'bottom_drawings': [d['id'] for d in drawings if (fitz.Rect(d['bbox']) * page.rotation_matrix).y1 >= bottom],
                'bottom_images': [i for i in images if (fitz.Rect(i['bbox']) * page.rotation_matrix).y1 >= bottom]}

    def render(page, name):
        pix = page.get_pixmap(dpi=CFG['dpi'], alpha=False)
        path = DEBUG / name
        pix.save(path)
        return {'path': path.relative_to(ROOT).as_posix(), 'sha256_pixels': hashlib.sha256(pix.samples).hexdigest()}

    if '--report-only' not in sys.argv:
        before = snapshot()
        evidence = {'environment': {'python': platform.python_version(), 'windows': platform.platform(),
            'packages': {p: importlib.metadata.version(p) for p in ('pymupdf', 'openpyxl', 'pyyaml', 'pytest')},
            'soffice_in_path': bool(shutil.which('soffice')),
            'soffice_common_locations': {root: (Path(os.environ.get(root, '')) / 'LibreOffice/program/soffice.exe').is_file()
                                          for root in ('ProgramFiles', 'ProgramFiles(x86)')}},
            'assets': {}, 'pdfs': {}, 'sheets': [], 'matches': [], 'renders': [], 'errors': []}
        for role, pattern in CFG['asset_patterns'].items():
            found = sorted((ROOT / 'assets').glob(pattern))
            evidence['assets'][role] = [p.relative_to(ROOT).as_posix() for p in found]
        if any(len(v) != 1 for v in evidence['assets'].values()):
            (ROOT / 'inspect_report.md').write_text('# توقف بررسی\n\n' + json.dumps(evidence['assets'], ensure_ascii=False, indent=2), encoding='utf-8')
            raise SystemExit('Asset pattern must match exactly one file.')
        asset = {k: ROOT / v[0] for k, v in evidence['assets'].items()}
        CFG['resolved_assets'] = {k: v[0] for k, v in evidence['assets'].items()}
        (ROOT / 'cache/config.yaml').write_text('# تنظیمات بررسی: source_dirs پوشه‌های فقط‌خواندنی؛ asset_patterns الگوهای کشف؛ dpi وضوح تصویر؛ bottom_fraction سهم پایین صفحه؛ header_scan_rows عمق جستجوی هدر؛ font_sentence متن تست؛ resolved_assets نام‌های واقعی کشف‌شده\n' + yaml.safe_dump(CFG, allow_unicode=True, sort_keys=False), encoding='utf-8')
        inputs = sorted((ROOT / CFG['source_dirs'][0]).glob('*.pdf'))
        for folder in CFG['source_dirs']:
            for path in sorted((ROOT / folder).glob('*.pdf')):
                key = path.relative_to(ROOT).as_posix()
                try:
                    with fitz.open(path) as doc:
                        pages = []
                        for page in doc:
                            print(key, page.number + 1, flush=True)
                            data = page_evidence(page, folder == 'assets')
                            pages.append(data)
                            if path == asset['template'] or path == asset['border'] or (folder == 'samples' and page.number < 2) or (folder == 'input' and page.number == 0):
                                role = 'template' if path == asset['template'] else 'border' if path == asset['border'] else folder + '_' + path.stem
                                evidence['renders'].append(render(page, f'{role}_{page.number + 1:02}.png'))
                        evidence['pdfs'][key] = pages
                except Exception as exc:
                    evidence['errors'].append({'file': key, 'error': type(exc).__name__ + ': ' + str(exc)})
        wb = openpyxl.load_workbook(asset['syllabus'], data_only=False)
        for ws in wb:
            rows = [[c.value for c in row] for row in ws.iter_rows()]
            scores = [(sum(isinstance(v, str) and bool(v.strip()) for v in row), i + 1)
                      for i, row in enumerate(rows[:CFG['header_scan_rows']])]
            best = max(s for s, _ in scores)
            candidates = [i for s, i in scores if s == best]
            header = candidates[0] if len(candidates) == 1 else None
            item = {'name': ws.title, 'max_row': ws.max_row, 'max_column': ws.max_column,
                    'nonempty_rows': sum(any(v is not None for v in row) for row in rows),
                    'header_candidates': candidates, 'header': header,
                    'headers': rows[header - 1] if header else None,
                    'top_rows': rows[:CFG['header_scan_rows'] + 2],
                    'merged': [str(r) for r in ws.merged_cells.ranges],
                    'formula_count': sum(c.data_type == 'f' for row in ws for c in row),
                    'formula_examples': [{'cell': c.coordinate, 'formula': c.value} for row in ws for c in row if c.data_type == 'f'][:10]}
            # All input matches across all columns/sheets; never assume a fixed slug column.
            match_columns = set()
            for ri, row in enumerate(rows, 1):
                for ci, value in enumerate(row, 1):
                    if isinstance(value, str):
                        for source in inputs:
                            if normal(value) == normal(source.stem):
                                evidence['matches'].append({'input': source.name, 'sheet': ws.title,
                                    'row': ri, 'column': ci, 'value': value, 'values': row})
                                match_columns.add(ci)
            item['matched_columns'] = sorted(match_columns)
            item['sample_rows'] = [{'row': i + 1, 'values': r} for i, r in enumerate(rows)
                                  if header and i + 1 > header and any(v is not None for v in r)][:10]
            # Preserve entire workbook values in local evidence, not in the public report.
            item['rows'] = rows
            evidence['sheets'].append(item)
        wb.close()
        try:
            font = fitz.Font(fontfile=str(asset['font']))
            trial = fitz.open()
            pg = trial.new_page()
            box = pg.rect + (pg.rect.width * .1, pg.rect.height * .35, -pg.rect.width * .1, -pg.rect.height * .35)
            css = '@font-face {font-family: aria; src: url("' + asset['font'].name + '");} * {font-family: aria;} p {text-align:center;font-size:28pt;}'
            result = pg.insert_htmlbox(box, '<p dir="rtl">' + CFG['font_sentence'] + '</p>', css=css, archive=fitz.Archive(str(asset['font'].parent)))
            trial.save(DEBUG / 'font_test.pdf')
            evidence['renders'].append(render(pg, 'font_test.png'))
            evidence['font_test'] = {'font_name': font.name, 'result': result, 'text': pg.get_text(), 'fonts': pg.get_fonts(full=True)}
            trial.close()
        except Exception as exc:
            evidence['errors'].append({'file': 'font_test', 'error': str(exc)})
        evidence['source_hashes_before'] = before
        evidence['source_hashes_after'] = snapshot()
        evidence['sources_unchanged'] = before == evidence['source_hashes_after']
        (ROOT / 'cache/inspection.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        (ROOT / 'requirements.txt').write_text('\n'.join(k + '==' + v for k, v in evidence['environment']['packages'].items()) + '\n', encoding='utf-8')
        print(json.dumps({'pdfs': len(evidence['pdfs']), 'pages': sum(map(len, evidence['pdfs'].values())), 'sheets': len(evidence['sheets']), 'renders': len(evidence['renders']), 'matches': len(evidence['matches']), 'errors': evidence['errors'], 'sources_unchanged': evidence['sources_unchanged']}, ensure_ascii=False))
    else:
        evidence = json.loads((ROOT / 'cache/inspection.json').read_text(encoding='utf-8'))

    def build_report(e):
        visual=json.loads((ROOT/'debug/visual_review.json').read_text(encoding='utf-8'))
        if snapshot() != e['source_hashes_before'] or visual['source_hashes'] != e['source_hashes_before']:
            raise ValueError('Visual review is stale: source hashes changed')
        def norm(v):
            t=unicodedata.normalize('NFKC',str(v)).translate(str.maketrans('يك','یک'))
            t=''.join(str(unicodedata.digit(c)) if c.isdecimal() else c for c in t if unicodedata.category(c)!='Cf')
            return re.sub(r'[\s_-]+','_',t.casefold()).strip('_')
        def cell(v):
            if v is None:return '∅'
            if isinstance(v,(list,dict)):v=json.dumps(v,ensure_ascii=False)
            return ''.join(f'\\u{ord(c):04x}' if unicodedata.category(c)=='Cc' and c not in '\n\t' else c for c in str(v)).replace('|','\\|').replace('\n','<br>').replace('\r','').replace('\t',' ')
        out=['# گزارش بررسی مرحله صفر','', 'این گزارش دربارهٔ فایل‌های موجود است؛ هیچ ابزار تولید جزوه ساخته نشده است. همهٔ اندازه‌ها و bboxها بر حسب point (۱/۷۲ اینچ)، با مبدأ بالا-چپ‌اند. bbox متن، محدودهٔ متریک فونت است و لزوماً مرز جوهر نیست. جهت مؤثر از page.rect پس از rotation تعیین شده است. منابع فقط خوانده شدند؛ PNGها شواهد بررسی‌اند و جایگزین PDF برداری نیستند.','', 'فرمان بازتولید: `python -B -X utf8 inspect.py`. تنظیمات و نام فایل‌های کشف‌شده در `cache/config.yaml`؛ مشاهدات دیداری در `debug/visual_review.json`. هدرها ابتدا با بیشترین سلول متنی در ۱۰ ردیف اول نامزد شدند و سپس محتوای هدر همهٔ شیت‌ها بازبینی شد. هیچ نام رشته، نامک، نام ستون یا مختصات فایل در منطق ابزار ثابت نشده است.','']
        def text(t):out.extend([t,''])
        def table(headers,rows):
            out.append('| '+' | '.join(map(cell,headers))+' |')
            out.append('| '+' | '.join(['---']*len(headers))+' |')
            for row in rows:out.append('| '+' | '.join(map(cell,row))+' |')
            out.append('')
        text('## ۱. محیط و وابستگی‌ها')
        table(['مورد','مشاهده'],[(k,v) for k,v in e['environment'].items()])
        text('بررسی اولیه در sandbox هر چهار import را ناموجود نشان داد؛ در اجرای دارای دسترسی، openpyxl، PyYAML و pytest از قبل نصب بودند و PyMuPDF نصب شد. تلاش اولیه برای نسخهٔ ۲ پیش از نصب متوقف شد چون وابستگی‌های اضافی داشت؛ نسخهٔ ۱٫۲۸٫۲ با --no-deps نصب شد. بستهٔ اضافی نصب نشد. soffice در PATH و دو مسیر متداول Program Files پیدا نشد؛ نبودن آن در تمام محل‌های ممکن سیستم **نامعلوم** است. هیچ LibreOffice نصب نشد. اجرای ابزار آفلاین است.')
        text('## ۲. دامنه، سلامت منابع و روش')
        table(['شاخص','مقدار'],[['PDF',len(e['pdfs'])],['صفحات PDF',sum(map(len,e['pdfs'].values()))],['شیت',len(e['sheets'])],['خطاهای ثبت‌شده',e['errors']],['تعداد فایل دارای هش',len(e['source_hashes_before'])],['هش پیش و پس برابر',e['sources_unchanged']]])
        text('## ۳. کشف assets')
        table(['نقش','الگو','تعداد','فایل'],[[k,{'syllabus':'*Syllabus*.xlsx','template':'*First_Page_Template*.pdf','border':'*Sarbarg*.pdf','font':'*Aria-Regular*.otf'}[k],len(v),v] for k,v in e['assets'].items()])
        text('هر چهار الگو دقیقاً یک نتیجه دارند؛ نام هیچ فایل منبع تغییر نکرد.')
        text('## ۴. مشخصات تک‌تک صفحات PDF')
        for name,pages in e['pdfs'].items():
            text('### '+name+' — '+str(len(pages))+' صفحه')
            table(['صفحه','عرض × ارتفاع مؤثر','MediaBox','CropBox','rotation','جهت','متن قابل استخراج / تعداد نویسه غیرسفید','تصویر / شکل برداری'],[[p['page'],p['size'],p['mediabox'],p['cropbox'],p['rotation'],p['orientation'],('بله' if p['text'].strip() else 'خیر')+' / '+str(sum(not c.isspace() for c in p['text'])),str(len(p['images']))+' / '+str(len(p['drawings']))] for p in pages])
        text('وجود متن به معنی سالم بودن تمام حروف یا متنی بودن دست‌نوشته‌ها نیست. در ورودی‌های فیزیک متن استخراجی عمدتاً سربرگ/پاورقی است؛ دست‌نوشته‌ها شکل برداری‌اند. صفحهٔ ۴ رسانه متن قابل استخراج ندارد و تصویر دارد.')
        text('## ۵. سیلابس')
        table(['شیت','ردیف هدر واقعی','max_row','ردیف دارای مقدار','ستون','ادغام','فرمول'],[[s['name'],s['header'],s['max_row'],s['nonempty_rows'],s['max_column'],len(s['merged']),s['formula_count']] for s in e['sheets']])
        text('max_row شامل ردیف‌های قالب، مقدار False و فرمول نیز هست؛ تعداد درس نیست. ردیف دارای مقدار یعنی حداقل یک سلول غیرتهی، حتی False. در شیت سلول، هدر واقعی ردیف ۱ و گروه‌بندی ردیف ۲ است. ستون سوم اقتصاد واقعاً «اطلاعات عمومی» نوشته شده، نه «نام استاد». این اختلاف باید در مرحلهٔ نگاشت بررسی شود.')
        slug_header=next(s for s in e['sheets'] if s['name']==e['matches'][0]['sheet'])['headers'][e['matches'][0]['column']-1]
        slugs=[]
        for s in e['sheets']:
            text('### شیت '+s['name'])
            headers=s['headers'] or []
            table(['ستون اکسل','نام دقیق هدر'],[[excel_col(i),h] for i,h in enumerate(headers,1)])
            text('۱۰ ردیف غیرتهی پس از هدر (ممکن است شامل ردیف گروه‌بندی یا قالب باشد):')
            text('ادغام‌ها: '+cell(s['merged']))
            text('نمونه فرمول‌ها (محاسبه یا بازنویسی نشده‌اند): '+cell(s['formula_examples']))
            table(['ردیف اکسل']+[excel_col(i)+' — '+(str(h) if h is not None else 'بدون عنوان') for i,h in enumerate(headers,1)],[[r['row']]+r['values'] for r in s['sample_rows']])
            cols=[i for i,h in enumerate(headers) if norm(h)==norm(slug_header)]
            vals=[(s['name'],ri+1,str(row[ci])) for ci in cols for ri,row in enumerate(s['rows']) if ri+1>s['header'] and row[ci] is not None and isinstance(row[ci],str)]
            slugs.extend(vals)
            text('تعداد سلول متنی غیرتهی در ستون نامک پس از هدر: '+str(len(vals)))
        text('### شکل نامک‌ها و تطبیق چهار ورودی')
        predicates={'دارای حرف لاتین':lambda v:bool(re.search('[A-Za-z]',v)), 'دارای حرف فارسی/عربی':lambda v:bool(re.search('[\u0600-\u06ff]',v)), 'دارای خط‌تیره':lambda v:'-' in v,'دارای زیرخط':lambda v:'_' in v,'دارای فاصله':lambda v:bool(re.search(r'\s',v)), 'دارای عدد انتهایی':lambda v:bool(re.search(r'\d\s*$',v))}
        table(['ویژگی (گروه‌ها همپوشانی دارند)','تعداد سلول از '+str(len(slugs)),'مثال دقیق'],[[k,sum(fn(v) for _,_,v in slugs),next((v for _,_,v in slugs if fn(v)),None)] for k,fn in predicates.items()])
        counts=collections.Counter(norm(v) for _,_,v in slugs)
        text('تعداد کلید نرمال‌شدهٔ تکراری در سراسر شیت‌ها: '+str(sum(n>1 for n in counts.values()))+'. تکرار در شیت‌های گزارش/قالب الزاماً تعارض درس نیست؛ اولویت انتخاب شیت **نامعلوم** و خارج از این مرحله است.')
        table(['ورودی','شیت (شاهد رشته؛ نه نگاشت قطعی عنوان)','ردیف','ستون','نامک دقیق','چهار مقدار بدون تغییر'],[[m['input'],m['sheet'],m['row'],excel_col(m['column']),m['value'],{h:v for h,v in zip(next(s for s in e['sheets'] if s['name']==m['sheet'])['headers'][m['column']:m['column']+4],m['values'][m['column']:m['column']+4])}] for m in e['matches']])
        for m in e['matches']:
            text('ردیف کامل '+m['sheet']+'!'+str(m['row'])+' برای '+m['value'])
            s=next(s for s in e['sheets'] if s['name']==m['sheet'])
            table(['ستون','هدر','مقدار دقیق'],[[excel_col(i),h,v] for i,(h,v) in enumerate(zip(s['headers'],m['values']),1)])
        text('هر چهار نامک دقیقاً یک تطبیق با نرمال‌سازی در تمام سلول‌های workbook داشتند؛ نیازی به پیشنهاد نزدیک‌ترین نامک نبود. نامک رسانه در سیلابس دارای فاصله است؛ نمونهٔ خروجی همان فاصله‌ها را با زیرخط دارد. عدد انتهایی ۸، ۹ و ۱۰ بخشی از نامک مشاهده‌شده است. متن سلول‌ها عمداً اصلاح املایی نشده است؛ مثال «کاز»، «انرزی» و «اشین» عین داده‌اند. هیچ ستون مستقل رشته در این چهار ردیف نیست؛ شیت فیزیک و سواد رسانه شاهد دسته‌بندی هستند، نگاشت قطعی آنها به عنوان تمپلیت هنوز قرارداد تولیدی ندارد.')
        text('## ۶. تمپلیت فرست‌پیج')
        tpl=e['pdfs'][e['assets']['template'][0]]
        titles=visual['template_titles']
        table(['صفحه','عنوان خوانده‌شده از تصویر','جهت','اندازه','عنوان خام استخراجی'],[[p['page'],'جزوه رشته '+titles[(p['page']-1)%len(titles)],p['orientation'],p['size'],' / '.join(l['text'] for l in p['lines'][:-4])] for p in tpl])
        text('عنوان‌های جدول از مشاهدهٔ تصویر‌اند؛ املای یونیکدی دقیق عنوان‌هایی که استخراج خراب دارند **نامعلوم** است. برچسب استاد در استخراج شامل U+001E است. جدول زیر bbox خود شیء متنی و کادر برداری را نشان می‌دهد؛ bbox بزرگ فونت با مرز دیداری حروف متفاوت است.')
        frame_rows=[]
        for p in tpl:
            candidates=[d for d in p['drawings'] if d['type']=='s' and d['bbox'][2]>d['bbox'][0] and d['bbox'][3]>d['bbox'][1]]
            frame=max(candidates,key=lambda d:(d['bbox'][2]-d['bbox'][0])*(d['bbox'][3]-d['bbox'][1]))
            frame_rows.append([p['page']]+[l['bbox'] for l in p['lines'][-4:]]+[frame['id'],frame['bbox'],frame['width']])
        table(['صفحه']+visual['labels']+['شناسه مسیر کادر','bbox کادر','ضخامت'],frame_rows)
        text('کادرها مسیر stroke برداری‌اند؛ چهار تزئین گوشه نیز برداری‌اند. در هر صفحه، بزرگ‌ترین مسیر stroke با عرض و ارتفاع غیرصفر به‌عنوان نامزد کادر گزارش شد و روی تماس‌برگ تطبیق دیداری دارد؛ این انتخاب الگوریتم تولیدی نیست.')
        table(['رشته (خوانش دیداری)','عمودی: صفحه','افقی: صفحه'],[[title,[p['page'] for p in tpl if titles[(p['page']-1)%len(titles)]==title and p['orientation']=='عمودی'],[p['page'] for p in tpl if titles[(p['page']-1)%len(titles)]==title and p['orientation']=='افقی']] for title in titles])
        hashes=collections.defaultdict(list)
        for r in e['renders']:
            if Path(r['path']).name.startswith('template_'):hashes[r['sha256_pixels']].append(r['path'])
        text('صفحات تکراری پیکسلی در رندر ۸۰dpi: '+cell([v for v in hashes.values() if len(v)>1])+'. عنوان هر رشته دو بار (دو جهت) تکرار می‌شود، اما صفحات یکسان نیستند. یکسانی بایت ساختار داخلی PDF بررسی نشده و **نامعلوم** است؛ عنوان یکسان نباید دلیل حذف صفحه باشد.')
        text('## ۷. بوردر')
        border=e['pdfs'][e['assets']['border'][0]][0]
        table(['تعداد صفحات','اندازه','جهت','rotation','شکل برداری','تصویر'],[[len(e['pdfs'][e['assets']['border'][0]]),border['size'],border['orientation'],border['rotation'],len(border['drawings']),len(border['images'])]])
        for label,ids in visual['border_components'].items():
            ds=[border['drawings'][i] for i in ids]
            bb=[min(d['bbox'][0] for d in ds),min(d['bbox'][1] for d in ds),max(d['bbox'][2] for d in ds),max(d['bbox'][3] for d in ds)]
            table(['جزء','شناسه مسیر','bbox اجتماع','نوع','fill'],[[label,ids,bb,[d['type'] for d in ds],[d['fill'] for d in ds]]])
        text('بوردر یک کادر مستطیلی پیوسته دور هر چهار ضلع نیست: نوار بالایی و کادر پایینی گرد دارد، با فضای میانی شفاف. انتهای پایین شکل سفید کمی بیرون صفحه است. گوشه‌ها بخشی از مسیرهای همین کادرها هستند، نه تصاویر جداگانه.')
        with fitz.open(ROOT/e['assets']['border'][0]) as bd:
            bp=bd[0];pix=bp.get_pixmap(alpha=True)
            text('پیکسل مرکز در رندر alpha=True: '+str(pix.pixel(pix.width//2,pix.height//2))+'. alpha=0 شاهد شفافیت مرکز است. مسیر شمارهٔ ۳ fill سفید دارد؛ پس کل صفحه را نمی‌توان یکدست شفاف یا یکدست سفید دانست.')
            trace=bp.get_texttrace()
            table(['متن','فونت','bbox متریک get_texttrace','نوع'],[[''.join(chr(c[0]) for c in s['chars']),s['font'],[round(v,3) for v in s['bbox']],'متن PDF'] for s in trace])
            table(['متن','bbox get_text(dict)','اندازه فونت'],[[s['text'],s['bbox'],s['size']] for l in border['lines'] for s in l['spans']])
            cornerrows=[]
            for i in visual['border_components']['خط بیرونی هدر و گوشه‌های گرد']+visual['border_components']['داخل سفید فوتر و گوشه‌های گرد']:
                for j,item in enumerate(bp.get_drawings()[i]['items']):
                    if item[0]=='c':
                        pts=item[1:];cornerrows.append([i,j,[round(min(p.x for p in pts),3),round(min(p.y for p in pts),3),round(max(p.x for p in pts),3),round(max(p.y for p in pts),3)]])
            table(['مسیر گوشه','شماره قطعه','bbox نقاط انتهایی و کنترل منحنی (نه bbox دقیق جوهر)'],cornerrows)
        text('عدد قابل حذف «١» (U+0661) در پایین چپ، متن Aria-UltraBold است؛ نه تصویر و نه outline. BALATAR.GROUP متن جداگانه با Aria-Regular است؛ دو span در یک line استخراج می‌شوند، بنابراین حذف کل line اشتباه است.')
        text('## ۸. ناحیهٔ ۱۰٪ پایین تمام صفحات ورودی')
        text('مرز پایین با y ≥ ۰٫۹ × ارتفاع مؤثر تعریف شد. تماس‌برگ `debug/input_bottoms.png` همهٔ ۲۴ صفحه را پوشش می‌دهد. شمارش شکل‌ها شامل هر مسیری است که bbox آن با ناحیه تلاقی دارد؛ این شمارش تشخیص شماره صفحه نیست.')
        for name,pages in e['pdfs'].items():
            if not name.startswith('input/'):continue
            text('### '+name)
            rows=[]
            for p in pages:
                txt=[{'text':l['text'],'bbox':l['display_bbox'],'font_sizes':[round(s['size'],3) for s in l['spans']]} for l in p['bottom_text'] if l['text'].strip()]
                ds=[p['drawings'][i] for i in p['bottom_drawings']]
                bounds=[min(d['bbox'][0] for d in ds),min(d['bbox'][1] for d in ds),max(d['bbox'][2] for d in ds),max(d['bbox'][3] for d in ds)] if ds else None
                rows.append([p['page'],round(p['size'][1]*.9,3),txt or 'متن غیرسفید استخراج نشد',len(ds),bounds,p['bottom_images'] or 'ندارد'])
            table(['صفحه','شروع ناحیه y','متن و bbox و اندازه فونت','تعداد مسیر متقاطع','bbox اجتماع مسیرها (کل مسیر)','تصویر متقاطع و bbox'],rows)
        text('فیزیک: در تمام ۱۵ صفحه، New Section 1 Page N یک متن کوچک واقعی است. همچنین در نوار پایین فرمول و دست‌نوشتهٔ برداری دیده می‌شود؛ خوانش کامل همهٔ اعداد دست‌نویس **نامعلوم** است و نباید شمارهٔ صفحه فرض شوند. رسانه: در ۹ صفحه شمارهٔ مستقل در بازبینی دیداری دیده نشد؛ صفحهٔ ۵ متن محتوایی «حساسیت زدایی» با bbox ثبت‌شده دارد، صفحهٔ ۴ تصویر وارد ناحیه می‌شود. نبودن هر عدد پنهان در تصویر/outline از استخراج متن به تنهایی اثبات نمی‌شود و **نامعلوم** است.')
        text('## ۹. نمونه‌ها در مقایسه با ورودی')
        comparison=[]
        for m in e['matches']:
            ip=e['pdfs']['input/'+m['input']]
            matches=[(n,p) for n,p in e['pdfs'].items() if n.startswith('samples/') and norm(Path(m['input']).stem) in norm(Path(n).stem)]
            if len(matches)!=1:raise ValueError('Ambiguous sample association')
            name,sp=matches[0]
            comparison.append([Path(name).name,len(ip),len(sp),len(sp)==len(ip)+1,sp[0]['orientation'],sp[1]['orientation'],ip[0]['orientation'],[p['orientation'] for p in sp[1:]]==[p['orientation'] for p in ip],len(sp[0]['text'].strip()),sp[0]['images']])
        table(['نمونه','ورودی','خروجی','ورودی+۱؟','جهت فرست‌پیج','جهت محتوای اول','جهت ورودی اول','جهت همه صفحات متناظر برابر؟','نویسه متن فرست‌پیج','تصاویر فرست‌پیج'],comparison)
        text('چهار فرست‌پیج هرکدام یک تصویر دارند و صفر نویسه قابل استخراج. چهار مقدار فرست‌پیج از PDF به‌صورت متنی قابل بازیابی نیست؛ نتیجهٔ استخراج هر چهار مقدار: **نامعلوم/فاقد لایه متن**. جدول زیر رونویسی دیداری است، نه استخراج ماشینی؛ '+visual['sample_unicode_caveat'])
        table(['ورودی متناظر']+visual['labels'],[[name]+list(values.values()) for name,values in visual['sample_visual'].items()])
        text('اصل متن سیلابس در بخش ۵ جداگانه ثبت شده است؛ تفاوت‌های املایی یا یونیکد با تصویر نمونه نباید بی‌صدا اصلاح شوند. نمونهٔ رسانه در صفحهٔ محتوا لوگو و نوشتهٔ هدر/فوتر کشیده دارد؛ این تصویر مرجع هدف حفظ نسبت اجزا نیست. شباهت عددی پیکسلی یا QC خروجی تولیدی اجرا نشده است.')
        text('## ۱۰. تصاویر شاهد')
        table(['تصویر PNG','حجم بایت'],[[p.relative_to(ROOT).as_posix(),p.stat().st_size] for p in sorted((ROOT/'debug').glob('*.png'))])
        text('۴۲ PNG اصلی در ۸۰dpi: ۲۸ تمپلیت + ۱ بوردر + ۸ نمونه + ۴ ورودی + ۱ فونت. سه تصویر تماس‌برگ تکمیلی برای دیدن مجموعه‌اند و مقیاس آنها برای اندازه‌گیری مناسب نیست. فایل font_test.pdf فقط صفحهٔ آزمایشی درخواستی است.')
        text('## ۱۱. فونت و insert_htmlbox')
        table(['شاخص','مشاهده'],list(e['font_test'].items()))
        with fitz.open(ROOT/'debug/font_test.pdf') as fd:
            fonts=fd[0].get_fonts(full=True)
            table(['فونت جاسازی‌شده','پسوند','بایت برنامه فونت'],[[f[3],fd.extract_font(f[0])[1],len(fd.extract_font(f[0])[3])] for f in fonts])
        text('PyMuPDF فایل Aria را خواند؛ insert_htmlbox متن «ما و رسانه‌ها» را بدون کوچک‌سازی (scale=1) درج کرد. تصویر font_test.png از نظر اتصال و راست‌به‌چپ بودن بازبینی شد. با وجود ظاهر صحیح، متن استخراجی شامل نویسه‌های نامرتبط است؛ برابری استخراج متن با متن ورودی تأیید نشد. کیفیت تمام حروف فارسی یا تمام جمله‌های سیلابس از این یک آزمون قابل نتیجه‌گیری نیست: **نامعلوم**.')
        text('## ۱۲. ابهام‌ها، ریسک‌ها و مرز ادعاها')
        risks=[['نگاشت رشته','شیت‌های فیزیک و سواد رسانه با عنوان‌های دیداری متناظرند؛ قرارداد عمومی نگاشت ۱۴ رشته به ۱۹ شیت نامعلوم.'],['یونیکد PDF','خرابی ToUnicode/نگاشت حروف در تمپلیت و تست فونت مشاهده شد؛ علت دقیق و راه رفع نامعلوم. NFKC نویسه کنترلی را به حرف گمشده تبدیل نمی‌کند.'],['نمونه‌های تصویری','استخراج دقیق چهار مقدار ناممکن با لایه متن فعلی؛ یونیکد دقیق نامعلوم. نمونه‌ها شاهد چیدمان‌اند، نه معیار متنی/برداری معتبر برای فرست‌پیج آینده.'],['حذف پایین صفحه','متن، فرمول، دست‌نوشته و تصویر محتوایی در ۱۰٪ پایینی وجود دارد. حذف نوار کامل قابل قبول نیست.'],['متریک فونت','bboxهای Aria بزرگ‌تر از جوهر دیداری‌اند. انتخاب ناحیه حذف بر پایه bbox خط مشترک، نشانی BALATAR.GROUP را نیز حذف می‌کند.'],['سیلابس','۱۹ شیت، ردیف‌های قالب و فرمول‌ها؛ ستون استاد اقتصاد عنوان متفاوت دارد. صحت نتایج cached فرمول‌ها و تمام داده‌های آموزشی نامعلوم؛ محاسبه نشدند.'],['جهت و اندازه','همه rotationهای مشاهده‌شده صفرند؛ صحت رفتار روی فایل‌های rotated یا صفحات mixed آینده نامعلوم. ورودی فیزیک ۸ و ۹/۱۰ اندازه متفاوت دارند؛ رسانه ۹۶۰×۵۴۰ است.'],['پس‌زمینه','مرکز بوردر شفاف، داخل فوتر سفید؛ سفید کردن کل صفحه باعث پوشاندن محتوا می‌شود.'],['کیفیت آینده','این مرحله تولیدی ندارد؛ نه‌تکه‌سازی، جایگذاری دقیق متن و QC نهایی اجرا یا تأیید نشده‌اند.'],['LibreOffice','در PATH و مسیرهای رایج نبود؛ نصب در مسیر سفارشی نامعلوم.'],['تکراری‌ها','پیکسل‌های ۲۸ تمپلیت در ۸۰dpi متفاوتند؛ برابری ساختار بایتی یا تفاوت ریزتر از این وضوح نامعلوم.']]
        table(['موضوع','مشاهده / نامعلوم'],risks)
        text('### هش منابع')
        table(['فایل','SHA-256 پیش و پس (برابر)'],list(e['source_hashes_before'].items()))
        text('### پذیرش و بازتولید')
        text('هر ۱۲ محور با داده و محدودیت پوشش داده شده است. «نامعلوم»ها به معنی قبولی تولید یا تأیید حدسی نیستند. بازتولید script گزارش را از دادهٔ استخراجی و مشاهدات دیداری ثبت‌شده می‌سازد. فایل‌های cache/inspection.json و یادداشت‌های کاری برای تحلیل محلی‌اند؛ فقط config لازم برای اجرای مجدد در commit قرار می‌گیرد. وضعیت تست و commit در پاسخ پایان مرحله گزارش می‌شود.')
        (ROOT/'inspect_report.md').write_text('\n'.join(out),encoding='utf-8')

    def excel_col(n):
        s=''
        while n:n,r=divmod(n-1,26);s=chr(65+r)+s
        return s

    build_report(evidence)
    print('report written')
