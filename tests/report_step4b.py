"""Report-only sample rendering; no acceptance threshold is derived from samples."""
import json
from pathlib import Path
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw
from syllabus import load_config, discover_assets, normalize_key
from pages import raster


def main():
    root=Path(__file__).resolve().parents[1];cfg=load_config()
    assets=discover_assets(cfg,root)
    output=root/cfg['paths']['output'];debug=root/cfg['paths']['debug']
    data=json.loads((output/'report.json').read_text(encoding='utf-8'))
    exclusions=json.loads((root/'tests/data/step4b_reference_policy.json').read_text(encoding='utf-8'))
    prefix=cfg['output_prefix']+'_';suffix='_'+cfg['output_version']
    samples={}
    for path in (root/cfg['paths']['samples']).glob('*.pdf'):
        if path.stem.startswith(prefix) and path.stem.endswith(suffix):
            key=normalize_key(path.stem[len(prefix):-len(suffix)])
            samples.setdefault(key,[]).append(path)
    rows=[]
    for item in data['items']:
        row={'namak':item['namak'],'input_pages':item['input_pages'],
             'qc':item.get('qc',{}).get('passed',False)}
        matches=samples.get(normalize_key(item['namak']),[])
        reason=exclusions.get(item['namak'])
        if not reason and len(matches)!=1:
            reason=f'نمونهٔ متناظر یکتا یافت نشد ({len(matches)} فایل)؛ مقایسه نامعلوم.'
        row['comparison_status']=reason or 'فقط گزارش؛ بدون شرط قبولی'
        with fitz.open(output/item['output']) as ours:
            a=raster(ours[0],cfg['cover']['qc_dpi'])
            images=[Image.fromarray(a)]
            if not reason:
                with fitz.open(matches[0]) as sample:
                    b=raster(sample[0],cfg['cover']['qc_dpi'])
                    images.append(Image.fromarray(b))
                    row['sample']=matches[0].relative_to(root).as_posix()
                    row['sizes_pt']=[list(ours[0].rect),list(sample[0].rect)]
                    # Anchor at the top left and pad only the diagnostic canvas;
                    # never resize either PDF render for the numeric comparison.
                    h=max(a.shape[0],b.shape[0]);w=max(a.shape[1],b.shape[1])
                    aa=np.full((h,w,3),255,np.uint8);bb=aa.copy()
                    aa[:a.shape[0],:a.shape[1]]=a;bb[:b.shape[0],:b.shape[1]]=b
                    diff=np.abs(aa.astype(np.int16)-bb.astype(np.int16))
                    row.update(different_pixels=int(np.any(diff,axis=2).sum()),
                        different_percent=float(np.any(diff,axis=2).mean()*100),
                        over_10_percent=float(np.any(diff>10,axis=2).mean()*100),
                        mean_channel_difference=float(diff.mean()),max_channel_difference=int(diff.max()))
            for image in images: image.thumbnail((850,1100))
            canvas=Image.new('RGB',(sum(im.width for im in images),max(im.height for im in images)+28),'white')
            draw=ImageDraw.Draw(canvas);x=0
            for j,im in enumerate(images):
                canvas.paste(im,(x,28));draw.text((x+5,5),'OURS' if j==0 else 'SAMPLE',fill='black');x+=im.width
            name='step4b_cover_'+Path(item['output']).stem+'.png'
            canvas.save(debug/name);row['image']='debug/'+name
        rows.append(row)
    (output/'step4b_comparisons.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# گزارش مرحلهٔ ۴b','',
        'مرجع رندر QC از همان سند مونتاژشده، پیش از save و با OutputIntents فرست‌پیج گرفته می‌شود. اختلاف پس از ذخیره باید دقیقاً صفر باشد؛ هیچ تلورانس اضافه نشده است. اثر تغییر کاتالوگ رنگ فقط گزارش می‌شود. منطق بوردر و اندازه/جای محتوا تغییر نکرده‌اند.','',
        'حذف شماره در پایین‌ترین ۸٪ ورودی انجام می‌شود. QC همان الگوی fullmatch را در پایین‌ترین ۱۵٪ خروجی بررسی می‌کند. پیشوند صفر تا سه واژه پیش از Page/صفحه و عدد مجاز است؛ تاریخ و جملهٔ ادامه‌دار شماره محسوب نمی‌شوند.','',
        '| نامک | صفحات ورودی / خروجی | QC | بیشترین اختلاف ذخیره (پیکسل) | اثر OutputIntents: بیشینه درصد پیکسل با اختلاف >۱۰ | هشدار تصویر (صفحه) |',
        '|---|---:|---|---:|---:|---:|']
    for item in data['items']:
        measured=[d['detail']['different_pixels'] for d in item.get('qc',{}).get('details',[]) if d['check'].endswith('رندر پس از مونتاژ')]
        image_pages={w['page'] for w in item['warnings'] if w['kind']=='image_number_unknown'}
        effect=max((e['percent_over_10'] for e in item.get('output_intents_effect',[])),default=0)
        lines.append(f"| {item['namak']} | {item['input_pages']} / {item['output_pages']} | {item['status']} | {max(measured) if measured else 'نامعلوم'} | {effect:.6f} | {len(image_pages)} |")
    lines+=['','## مقایسهٔ فرست‌پیج با sample','',
        'رندر RGB در وضوح config (۱۵۰ dpi)، بدون تغییر اندازه، با هم‌ترازی گوشهٔ بالا/چپ. در صورت تفاوت ابعاد، فقط بوم اندازه‌گیری با سفید پر می‌شود. درصد اختلاف شامل همهٔ پیکسل‌های بوم است؛ کیفیت نمونه شرط پذیرش نیست. تصاویر نمایش کوچک شده‌اند ولی اعداد از رندر اصلی‌اند.','',
        '| نامک | اختلاف پیکسل ٪ | اختلاف بیش از ۱۰ ٪ | وضعیت |','|---|---:|---:|---|']
    for row in rows:
        percent=f"{row['different_percent']:.4f}" if 'different_percent' in row else '—'
        over=f"{row['over_10_percent']:.4f}" if 'over_10_percent' in row else '—'
        lines.append(f"| {row['namak']} | {percent} | {over} | {row['comparison_status']} |")
    lines+=['','### اندازهٔ فرست‌پیج‌ها (پوینت)','',
        '| نامک | تولید: عرض × ارتفاع | sample: عرض × ارتفاع |','|---|---:|---:|']
    for row in rows:
        if 'sizes_pt' in row:
            a,b=row['sizes_pt']
            lines.append(f"| {row['namak']} | {a[2]:.3f} × {a[3]:.3f} | {b[2]:.3f} × {b[3]:.3f} |")
    lines+=['','بازبینی دیداری ۱۳ تصویر: حروف فارسی پیوسته‌اند. فرست‌پیج‌های اقتصاد تولیدشده ۸۴۱٫۸۹×۵۹۵٫۲۷۶ هستند، ولی نمونه‌های GO و M15 برابر ۹۶۰×۵۴۰ و M12 برابر ۱۳۷۶×۷۶۸ هستند؛ تفاوت نسبت‌ها و چیدمان در تصویر دیده می‌شود و مقایسهٔ پیکسلی هم‌اندازه نیست. در نجوم و ترمودینامیک ۸ و ۹، شکست سطرهای مبحث با sample تفاوت دارد. علت دقیق روش تولید sample نامعلوم است؛ فونت، مقیاس و چیدمان تولید برای کاهش عدد اختلاف تغییر نکرده‌اند.']
    lines+=['','## حذف شماره و هشدارها','']
    for item in data['items']:
        removed=[f"صفحه {p['page']}: {r['text']}" for p in item['pages'] for r in p['removed']]
        if removed: lines.append(f"- {item['namak']}: "+'؛ '.join(removed))
    lines+=['','هشدارهای image_number_unknown در report.txt برای هر فایل یک خط‌اند؛ علت قطعی هشدار، تصویر کوچک در پایین صفحه است. ماهیت آن‌ها (شماره/واترمارک یا محتوای دیگر) بدون مشاهدهٔ قطعی نامعلوم ثبت شده؛ هیچ تصویری حذف نشده است. جزئیات خام در report.json حفظ شده‌اند.','',
        '## منابع کشف‌شده','']
    lines += [f'- {key}: `{path.relative_to(root).as_posix()}`' for key,path in assets.items()]
    lines+=['','## محدودیت‌های مقایسه','',
        'برای شیمی ۷ طبق اعلام کاربر sample جفت نیست و مقایسه انجام نشده است. برای هر نامک بدون sample متناظر، عدد مقایسه نامعلوم است؛ جفت‌کردن حدسی انجام نمی‌شود. تفاوت تصویری نمونه و تولید می‌تواند در اندازه/محل متن و روش رندر دیده شود؛ علت دقیق بدون شاهد نامعلوم است.','',
        'شواهد عددی کامل: output/report.json و output/step4b_comparisons.json. تصاویر: debug/step4b_cover_*.png. نتیجهٔ اجرای نهایی pytest در پایان این گزارش ثبت می‌شود.']
    (output/'step4b_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__': main()
