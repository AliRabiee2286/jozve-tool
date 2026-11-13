"""Legacy text/JSON report writer kept byte-compatible with the old CLI."""

import json

from syllabus import load_config


def write_report(output, items, global_warnings):
    lines=['گزارش پردازش جزوه‌ها','']
    lines.extend('هشدار سیلابس: '+w for w in global_warnings)
    for item in items:
        lines+=['',f"{item['status']}: {', '.join(item['files'])}"]
        for key,label in [('namak','نامک'),('sheet','رشته'),('orientation','جهت'),('input_pages','صفحات ورودی'),('output_pages','صفحات خروجی'),('seconds','زمان (ثانیه)'),('output','نام خروجی'),('error','علت خطا')]:
            if key in item:
                value={'portrait':'عمودی','landscape':'افقی'}.get(item[key],item[key]) if key=='orientation' else item[key]
                lines.append(f'{label}: {value}')
        if item.get('kind') and item['kind'] in load_config()['qa']['kinds']:
            cfg=load_config();lines.append('نوع: '+cfg['qa']['kinds'][item['kind']]['title'])
            lines.extend(cfg['headers'][k][0]+': '+str(v.get('value') or '') for k,v in item.get('cover',{}).get('fields',{}).items())
        for key,passed in item.get('qc',{}).get('checks',{}).items(): lines.append(f"  {key}: {'قبول' if passed else 'رد'}")
        if item.get('qc',{}).get('blocking_failed'):
            lines.append('کنترل‌های بلاک‌کنندهٔ ردشده: '+', '.join(item['qc']['blocking_failed']))
        if item.get('qc',{}).get('advisory_failed'):
            lines.append('کنترل‌های توصیه‌ای ردشده: '+', '.join(item['qc']['advisory_failed']))
        for detail in item.get('qc',{}).get('details',[]): lines.append(json.dumps(detail,ensure_ascii=False))
        image_warnings=[w for w in item.get('warnings',[]) if w['kind']=='image_number_unknown']
        if image_warnings:
            affected=sorted({w['page'] for w in image_warnings})
            lines.append(f'شمارهٔ تصویری نامعلوم: {len(affected)} صفحه ({", ".join(map(str,affected))})؛ '
                         'علت هشدار: تصویر کوچک در پایین صفحه؛ ماهیت تصویر نامعلوم؛ تصویر حذف نشد.')
        for warning in item.get('warnings',[]):
            if warning['kind']=='empty_cover_fields':
                cfg=load_config()
                names='، '.join(cfg['headers'][field][0] for field in warning['fields'])
                lines.append('مقدار خالی در سیلابس: '+names)
            elif warning['kind']=='syllabus_source_conflict':
                lines.append('هشدار تعارض سیلابس: مقدار شیت رشته‌ای معتبر است؛ '
                             'syllabus source conflict: subject sheet takes priority')
            elif warning['kind']!='image_number_unknown':
                lines.append('هشدار: '+json.dumps(warning,ensure_ascii=False))
        for effect in item.get('output_intents_effect',[]):
            lines.append('اثر OutputIntents (صرفاً گزارش): '+json.dumps(effect,ensure_ascii=False))
        for page in item.get('pages',[]):
            for removed in page['removed']: lines.append(f"حذف شمارهٔ متنی صفحه {page['page']}: {removed['text']}")
        if item['status']=='خطا': lines.append('اگر خروجی قدیمی وجود دارد، نتیجهٔ این اجرا نیست و بازنویسی نشده است.')
    success=sum(i['status']=='موفق' for i in items)
    review=sum(i['status']=='بازبینی' for i in items)
    blocked=sum(i['status']=='خطا' for i in items)
    review_items=[i for i in items if i['status']=='بازبینی']
    if review_items:
        review_lines=['گزارش فایل‌های نیازمند بازبینی','']
        for item in review_items:
            review_lines.append('فایل: '+item.get('output',', '.join(item['files'])))
            review_lines.append('کنترل‌های ردشده:')
            for control in item.get('qc',{}).get('advisory_failed',[]):
                review_lines.append(f'- {control}: کنترل توصیه‌ای رد شده است؛ فایل منتشر شده و بازبینی دیداری لازم است.')
            if item.get('review_image'):
                review_lines.append('تصویر مرور: '+item['review_image'])
            review_lines.append('')
        (output/'REVIEW.txt').write_text('\n'.join(review_lines),encoding='utf-8-sig')
    else:
        (output/'REVIEW.txt').unlink(missing_ok=True)
    summary=f'خلاصه: {success} موفق؛ {review} بازبینی؛ {blocked} خطا | OK={success} REVIEW={review} BLOCKED={blocked}'
    lines+=['',summary]
    (output/'report.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8-sig')
    (output/'report.json').write_text(json.dumps({'items':items,'summary':summary,
        'counts':{'OK':success,'REVIEW':review,'BLOCKED':blocked}},ensure_ascii=False,indent=2),encoding='utf-8')
    return summary
