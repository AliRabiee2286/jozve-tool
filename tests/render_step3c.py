"""Rebuild step 3c review sheets from pytest-generated PDFs and measurements."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
import pymupdf as fitz
from syllabus import load_config, discover_assets
from pages import raster


def main():
    root=Path(__file__).resolve().parents[1];cfg=load_config()
    assets=discover_assets(cfg,root)
    debug=root/cfg['paths']['debug'];cache=root/cfg['paths']['cache']
    reports=[];comparisons=[];details=[]
    # Explicit review selections requested by the user, not production rules.
    selected={'physics_thermo_8':{4},'physics_thermo_9':{1,3},'Savad_resane-ma_va_resane-10':{1}}
    for src in sorted((root/cfg['paths']['input']).glob('*.pdf')):
        slug=src.stem.replace(' ','_')
        read=lambda suffix:json.loads((debug/f'fit_{slug}_{suffix}.json').read_text(encoding='utf-8'))
        report=read('qc');renders=read('render');exteriors=read('exterior')
        for p,r,e in zip(report['pages'],renders,exteriors):
            assert p['page']==r['page']==e['page']
            p['render_comparison']=r;p['exterior_comparison']=e
            assert not any(x['meaningful_ink_pixels'] for x in p['coverage_after_fit'])
            comparisons.append(debug/f'fit_{slug}_p{p["page"]}.png')
        reports.append(report)
        sample=root/cfg['paths']['samples']/f"{cfg['output_prefix']}_{slug}_{cfg['output_version']}.pdf"
        with fitz.open(cache/f'fit_{slug}.pdf') as ours,fitz.open(sample) as theirs:
            for page_number in selected.get(slug,[]):
                ims=[Image.fromarray(raster(ours[page_number-1],200)),Image.fromarray(raster(theirs[page_number],200))]
                canvas=Image.new('RGB',(sum(i.width for i in ims),max(i.height for i in ims)+28),'white')
                canvas.paste(ims[0],(0,28));canvas.paste(ims[1],(ims[0].width,28))
                ImageDraw.Draw(canvas).text((8,5),f'{slug} p{page_number}: FITTED LEFT / SAMPLE RIGHT; 200 dpi',fill='black')
                name=f'fit_detail_{slug}_p{page_number}.png';canvas.save(debug/name);details.append(name)
    contacts=[]
    for start in range(0,len(comparisons),8):
        batch=comparisons[start:start+8];thumbs=[]
        for path in batch:
            with Image.open(path) as image:
                image.thumbnail((1000,810));thumbs.append(image.copy())
        heights=[max(i.height for i in thumbs[j:j+2])+28 for j in range(0,len(thumbs),2)]
        canvas=Image.new('RGB',(2000,sum(heights)),'white')
        for j,(path,image) in enumerate(zip(batch,thumbs)):
            x=j%2*1000;y=sum(heights[:j//2])
            canvas.paste(image,(x,y+28));ImageDraw.Draw(canvas).text((x+5,y+5),path.stem,fill='black')
        name=f'fit_contact_{start//8+1}.png';canvas.save(debug/name)
        contacts.append({'image':name,'pages':[p.name for p in batch]})
    assert len(comparisons)==24 and len(contacts)==3
    (debug/'step3c_manifest.json').write_text(json.dumps({'contacts':contacts,'details':details,'reports':reports},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# گزارش مرحلهٔ ۳c — جای‌گذاری برداری میان نوارها','',
           'ترتیب اجرا: کپی برداری و حفظ Group/OutputIntents ← bake ← حذف شماره ← مقیاس یکنواخت محتوا ← بوردر. قاعدهٔ ۶ AGENTS.md طبق مجوز کاربر به‌روز شد. حاشیهٔ بالا و پایین هر کدام ۴ پوینت و قابل تنظیم در config هستند. اندازهٔ صفحه، MediaBox، CropBox و rotation تغییر نمی‌کنند. تبدیل q/cm/Q روی streamهای موجود اعمال می‌شود؛ تصویر یا گروه شفافیت جدید برای محتوا ساخته نمی‌شود. کلیپِ محدودهٔ اصلی مانع ظاهرشدن محتوای قبلاً بیرون صفحه می‌شود.','',
           'c=min(1, ارتفاع امن/ارتفاع مؤثر صفحه). عرض و ارتفاع با یک c تغییر می‌کنند، محتوا افقی وسط است؛ صفحات هم‌اندازه c یکسان دارند. ناحیهٔ امن با پایین واقعی هدر و بالای واقعی فوتر محاسبه می‌شود.','',
           '## جدول همهٔ صفحات','',
           'رندر در ۱۵۰dpi است. مرجعِ رنگ، همان صفحه پس از bake و حذف شماره است که ماتریس مقیاس/جای‌گذاری را مستقیماً به دستگاه رسم MuPDF می‌دهد؛ خروجی تبدیل‌شده بدون بوردر با همان دستگاه رسم می‌شود. این مرجع از تبدیل مختصات PDF در کد تولید مستقل است. حد مجاز هر کانال ۲، فقط لبه‌ها؛ در داده‌های زیر بیشینه و تعداد پیکسل متفاوت ثبت شده‌اند. مقایسهٔ بیرون نوارها از get_pixmap با نسخهٔ مقیاس‌شدهٔ بدون بوردر استفاده می‌کند و همچنان دقیقاً صفر لازم است.','',
           '| فایل | صفحه | c | هدر: جوهر | فوتر: جوهر | بیشینه اختلاف رنگ | پیکسل متفاوت رنگ | بیرون نوارها |',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in reports:
        for p in r['pages']:
            counts={x['strip']:x['meaningful_ink_pixels'] for x in p['coverage_after_fit']}
            color=p['render_comparison'];ex=p['exterior_comparison']
            lines.append(f'| {r["source"]} | {p["page"]} | {p["fit"]["scale"]:.9f} | {counts["header"]} | {counts["footer"]} | {color["max_channel_difference"]} | {color["different_pixels"]} | {ex["outside_strip_differences"]} |')
    lines+=['','## پذیرش و حفظ محتوا','','| فایل | صفحات | تعداد/هندسه | حذف شماره | متن محتوا | BALATAR.GROUP |','|---|---:|---|---|---|---|']
    for r in reports:
        checks=r['checks'];passed=lambda v:'قبول' if v else 'رد'
        lines.append(f'| {r["source"]} | {len(r["pages"])} | {passed(checks["a_count"] and checks["b_geometry"])} | {passed(checks["c_no_number_text"])} | {passed(checks["d_same_content_text"])} | {passed(checks["e_footer_text"])} |')
    lines+=['','هش SHA-256 تصاویر استخراج‌شده برای هر صفحه قبل/بعد برابر است؛ stream تصاویر پیش/پسِ fit نیز یکسان است. متن دقیقاً پس از حذف موارد گزارش‌شده و BALATAR.GROUP مقایسه شده، نه صرفاً تعداد کاراکتر. کلاهک‌های شش تکهٔ بوردر همان کد آزموده‌شدهٔ مرحلهٔ ۳ هستند؛ scale_x=scale_y برای هر کلاهک برقرار است. معیار جوهر ۳b تغییر نکرد. همهٔ ۴۸ ناحیهٔ هدر/فوتر جوهر صفر دارند؛ crop هم‌پوشانی لازم نشد.','','## منابع یکتا']
    lines += [f'- {key}: `{path.relative_to(root).as_posix()}`' for key,path in assets.items()]
    lines+=['','## تصاویر','', 'در همهٔ مقایسه‌ها تولید ما چپ و sample راست است. اختلاف اندازهٔ محتوا با sample عمدی و نتیجهٔ مجوز کوچک‌سازی است. سه تماس‌برگ تمام ۲۴ صفحه را در گروه‌های هشت‌تایی دارند؛ چهار تصویر ۲۰۰dpi برای بازبینی بزرگ‌شده ساخته شده است.','']
    lines += [f'- `debug/{c["image"]}`' for c in contacts]+[f'- `debug/{name}`' for name in details]
    lines+=['','## حدود شواهد و نامعلوم‌ها','',
            'رندر مستقیم هر دو طرف از یک موتور استفاده می‌کند؛ برابری در تمام نرم‌افزارهای نمایش PDF بررسی نشده است. مسیر رندر واسط DisplayList در آزمایش اولیهٔ صفحهٔ اول دو فایل اختلاف لبه‌ای تا ۱۷ داشت، در حالی که رندر مستقیم همان محتوا برابر بود؛ علت دقیق اختلاف مسیر واسط نامعلوم است و هیچ تلورانسی برای پذیرش آن اضافه نشده است. این اختلاف نباید به‌عنوان تغییر رنگ واقعی محتوا یا دلیل اثبات‌شدهٔ آنتی‌الیاس گزارش شود.',
            '', 'فایل‌های واقعی widget ندارند؛ کیفیت جای‌گذاری فرم تعاملی تأیید نشده است. تصویر دارای شماره با OCR بررسی/حذف نمی‌شود؛ وضعیت شمارهٔ تصویری نامعلوم است و تصویر دست‌نخورده می‌ماند. تعریف رنگی جوهر همان محدودیت ۳b را دارد: جوهر هم‌رنگ خطوط کاغذ را از خود خطوط تشخیص نمی‌دهد.',
            '', 'این مرحله فقط صفحات محتواست؛ PDFهای cache/fit_*.pdf فرست‌پیج ندارند. نتیجهٔ اجرای نهایی pytest و وضعیت commit/push در پاسخ پایان مرحله ثبت می‌شود.']
    (root/cfg['paths']['output']/'step3c_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
