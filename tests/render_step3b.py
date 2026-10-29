"""Rebuild review images and Persian tables from the tested content PDFs.

Run from project root: python -c "import runpy; runpy.run_path('tests/render_step3b.py', run_name='__main__')"
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz
from syllabus import load_config, discover_assets
from pages import raster, meaningful_ink
from border import apply_border


def panel(images, label, scale=1):
    if scale != 1:
        images=[im.resize((im.width*scale,im.height*scale),Image.Resampling.NEAREST) for im in images]
    canvas=Image.new('RGB',(sum(im.width for im in images),max(im.height for im in images)+28),'white')
    x=0
    for im in images:
        canvas.paste(im,(x,28));x+=im.width
    ImageDraw.Draw(canvas).text((5,5),label,fill='black')
    return canvas


def main():
    cfg=load_config();root=Path(__file__).resolve().parents[1]
    assets=discover_assets(cfg,root)
    debug=root/cfg['paths']['debug'];cache=root/cfg['paths']['cache']
    reports=[];comparisons=[];crop_files=[];header_check=None
    for src in sorted((root/cfg['paths']['input']).glob('*.pdf')):
        slug=src.stem.replace(' ','_')
        report=json.loads((debug/f'border_{slug}_qc.json').read_text(encoding='utf-8'))
        reports.append(report)
        with fitz.open(src) as original, fitz.open(cache/f'border_{slug}.pdf') as out:
            for i,(p,q,entry) in enumerate(zip(original,out,report['pages'])):
                comparisons.append(debug/f'border_{slug}_p{i+1}.png')
                before=raster(p,cfg['pages']['diagnostic_dpi'])
                after=raster(q,cfg['pages']['diagnostic_dpi'])
                for region in entry['coverage_after_number_removal']:
                    x0,y0,x1,y1=(fitz.Rect(region['bbox'])*(cfg['pages']['diagnostic_dpi']/72)).irect
                    x0,y0=max(0,x0),max(0,y0);x1,y1=min(before.shape[1],x1),min(before.shape[0],y1)
                    name=f'ink_{slug}_p{i+1}_{region["strip"]}.png'
                    panel([Image.fromarray(before[y0:y1,x0:x1]),Image.fromarray(after[y0:y1,x0:x1])],
                          f'{slug} p{i+1} {region["strip"]}: INPUT / OUTPUT; ink after number removal={region["meaningful_ink_pixels"]}',2).save(debug/name)
                    if region['meaningful_ink_pixels']:
                        crop_files.append(name)
                if i==0:
                    mask=meaningful_ink(before,cfg['pages'])
                    selected=np.full_like(before,255);selected[mask]=before[mask]
                    proof=panel([Image.fromarray(before),Image.fromarray(selected)],f'{slug}: INPUT / INK (min < 194; paper-margin blends excluded)')
                    proof.thumbnail((1800,1600))
                    proof.save(debug/f'ink_calibration_{slug}.png')
                if slug=='physics_thermo_10' and i==3:
                    header=next(r for r in entry['coverage_original'] if r['strip']=='header')
                    x0,y0,x1,y1=(fitz.Rect(header['bbox'])*(cfg['pages']['diagnostic_dpi']/72)).irect
                    # Left is the source including its white annotations; right is baked then bordered.
                    panel([Image.fromarray(before[y0:y1,x0:x1]),Image.fromarray(after[y0:y1,x0:x1])],
                          'physics_thermo_10 p4: ORIGINAL / BAKED THEN BORDERED',2).save(debug/'baked_header_physics_thermo_10_p4.png')
                    with fitz.open() as empty, fitz.open(cache/cfg['border']['clean_filename']) as clean:
                        reference=empty.new_page(width=q.rect.width,height=q.rect.height)
                        apply_border(reference,clean,cfg['border'])
                        ref=raster(reference,cfg['pages']['diagnostic_dpi'])[y0:y1,x0:x1]
                        actual=after[y0:y1,x0:x1]
                        green=(ref[:,:,1]>ref[:,:,0]) & (ref[:,:,1]>ref[:,:,2]) & (ref[:,:,0]<194)
                        holes=int(np.sum(green & (np.min(actual,axis=2)>245)))
                        assert holes==0, 'Unexpected white annotation over the header'
                        header_check={'reference_green_pixels':int(green.sum()),'unexpected_white_pixels':holes}
    contacts=[]
    for start in range(0,len(comparisons),8):
        batch=comparisons[start:start+8]
        thumbs=[]
        for path in batch:
            image=Image.open(path);image.thumbnail((1000,810));thumbs.append(image.copy())
        heights=[max(im.height for im in thumbs[j:j+2])+28 for j in range(0,len(thumbs),2)]
        canvas=Image.new('RGB',(2000,sum(heights)),'white')
        for j,(path,image) in enumerate(zip(batch,thumbs)):
            x=(j%2)*1000;y=sum(heights[:j//2])
            canvas.paste(image,(x,y+28));ImageDraw.Draw(canvas).text((x+5,y+5),path.stem,fill='black')
        name=f'border_step3b_contact_{start//8+1}.png';canvas.save(debug/name)
        contacts.append({'image':name,'pages':[p.name for p in batch]})
    (debug/'step3b_manifest.json').write_text(json.dumps({'contacts':contacts,'overlap_crops':crop_files,'header_check':header_check},ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# گزارش تکمیل اصلاحات مرحلهٔ ۳b','','محتوا کوچک یا جابه‌جا نشده است. bake فقط روی نسخهٔ خروجی، پیش از حذف شماره و بوردر انجام می‌شود؛ annotationها برداری داخل محتوا قرار می‌گیرند. widgets=False است و وجود widget گزارش می‌شود؛ bake برای فایل دارای widget نیز اجرا می‌شود.','','## معیار bake و حفظ محتوا','','حداکثر اختلاف مجاز هر کانال ۲ و فقط داخل bbox annotation با حاشیهٔ ۳ پیکسل است. بیرون این محدوده اختلاف صفر است. تعداد تصاویر و شکل‌ها و متن و تعداد widgetها برابر می‌مانند. منبع کنترل صفر تغییر در مرحلهٔ حذف شماره/بوردر، نسخهٔ **پس از bake** است؛ خود bake جداگانه با معیار مجاز کاربر کنترل شده است. هیچ تلورانسی به آزمون بوردر افزوده نشده است.','', 'علت دقیق اختلاف تک‌واحدی **نامعلوم** است؛ محصوربودن آن در ناحیه annotation به‌تنهایی اثبات علت آنتی‌الیاس نیست.','','| فایل | صفحه | annotation تبدیل‌شده | اختلاف کانال حداکثر | پیکسل متفاوت | بیرون bbox+3 | widget قبل/بعد |','|---|---:|---:|---:|---:|---:|---|']
    for r in reports:
        for p in r['pages']:
            b=p['bake'];lines.append(f'| {r["source"]} | {p["page"]} | {b["annotations_before"]} | {b["max_channel_difference"]} | {b["different_pixels"]} | {b["outside_annotation_pixels"]} | {b["widgets_before"]}/{b["widgets_after"]} |')
    lines+=['','## جوهر معنادار','','رنگ مسیرهای افقی تکرارشوندهٔ هر ۱۵ صفحه فیزیک، پس از گردکردن RGB×255، برابر (202,235,253) است. تعداد خطوط تشخیص‌داده‌شده در هر صفحه در JSON ثبت شده است. در رسانه خط کاغذ تکرارشونده پیدا نشد؛ همان آستانهٔ کالیبره‌شده استفاده می‌شود و رنگی برای خطوط آن حدس زده نمی‌شود.','','تعریف ثابت: min(R,G,B) < 202−8 = 194، به‌جز رنگ خطوط کاغذ و ترکیب آن‌ها با سفید یا با یکدیگر در تقاطع‌ها، با فاصلهٔ حداکثر ۲ در هر کانال. رنگ خط عمودی قرمز (255,80,80) است. تقاطع‌های اندازه‌گیری‌شده مانند (227,169,177) و (248,97,99) با مدل ترکیب ضربی دو رنگ کنار می‌روند؛ نمونه‌های همین رنگ‌ها در آزمون طبقه‌بندی ثبت شده‌اند. رنگ خط عمودی نیز از مسیر برداری ورودی اندازه‌گیری شد؛ تنها معیار اول این خط را به‌اشتباه جوهر می‌شمرد. خطوط آبی و حاشیهٔ قرمز کاغذ کنار می‌روند؛ جوهرهای پررنگ قرمز، آبی، سبز، مشکی و بدنهٔ شکل‌ها باقی می‌مانند. این تعریف رنگی است، نه تشخیص معنای متن؛ جوهر بسیار کم‌رنگ یا هم‌رنگ خط حاشیه ممکن است کنار برود؛ متن قرمز پررنگ و بدنهٔ خاکستری (81,81,81) در آزمون رنگ حفظ می‌شوند. آستانه برای صفرکردن هم‌پوشانی تغییر داده نشده است.','','شمارش زیر در ۱۵۰dpi، جهت مؤثر و اندازه واقعی نوارها، روی محتوای پس از bake و حذف شماره، پیش از بوردر انجام شده است. شمارش پیش از حذف شماره نیز در JSON موجود است.','','| فایل | صفحه | هدر | فوتر |','|---|---:|---:|---:|']
    for r in reports:
        for p in r['pages']:
            counts={v['strip']:v['meaningful_ink_pixels'] for v in p['coverage_after_number_removal']}
            lines.append(f'| {r["source"]} | {p["page"]} | {counts["header"]} | {counts["footer"]} |')
    lines+=['','## معیارهای الف تا ه و تصاویر کامل','','| فایل | تعداد صفحات | الف | ب | ج | د | ه | صفحات مقایسه |','|---|---:|---|---|---|---|---|---|']
    for r in reports:
        checks=r['checks'];lines.append('| '+r['source']+' | '+str(len(r['pages']))+' | '+' | '.join('قبول' if checks[k] else 'رد' for k in ['a_count','b_geometry','c_no_number_text','d_same_content_text','e_footer_text'])+' | '+', '.join(map(str,checks['f_comparison_pages']))+' |')
    lines+=['','۲۴ تصویر کامل در سه تماس‌برگ هشت‌صفحه‌ای قرار گرفته‌اند؛ صفحات ۲ و ۴ فیزیک ۸ نیز حاضرند و جای هر صفحه در manifest مشخص است. در مقایسه‌های کامل تولید ما چپ و sample راست است. در cropهای جوهر، ورودی چپ و تولید ما راست است. هر نوار دارای جوهر غیرصفر crop با بزرگ‌نمایی دوبرابر دارد.','']
    lines += ['- `debug/'+c['image']+'`' for c in contacts]
    lines+=['- `debug/baked_header_physics_thermo_10_p4.png`: شاهد هدر پس از bake.','- `debug/ink_calibration_*.png`: چهار شاهد بصری آستانه.','- `debug/ink_*_pN_header.png` و `debug/ink_*_pN_footer.png`: cropهای هم‌پوشانی؛ فهرست دقیق در manifest.','','## منابع و وضعیت','','همهٔ الگوهای منابع از config خوانده شدند و دقیقاً یک نتیجه دارند:']
    lines += [f'- {k}: `{v.relative_to(root).as_posix()}`' for k,v in assets.items()]
    lines+=['',f'کنترل مستقل هدر فیزیک ۱۰ صفحهٔ ۴: {header_check["reference_green_pixels"]} پیکسل سبز مرجع بررسی شد؛ سفیدِ غیرمنتظره روی آن‌ها: {header_check["unexpected_white_pixels"]}.',
            '', 'در آزمون مصنوعی یک widget و یک annotation، bake اجرا شد و widget حفظ شد، اما تعداد شکل‌ها از ۱ به ۲ رفت؛ این ورودی طبق قرارداد کنترل کیفیت رد می‌شود. این آزمونِ انتظارِ رد قبول است و معیار ساختاری شل نشده است. همهٔ ورودی‌های واقعی فاقد widget هستند.',
            '', 'هم‌پوشانی جوهر معنادار همچنان وجود دارد. طبق دستور کاربر فقط گزارش شده و هیچ تغییر اندازه، جای‌گذاری، پاک‌کردن یا اقدام جبرانی انجام نشده است. تصمیم درباره پذیرش هم‌پوشانی با کاربر است؛ خروجی نهایی موفق اعلام نشده است.','','آزمون‌ها: نتیجهٔ اجرای نهایی در پاسخ مرحله ثبت می‌شود. بازتولید تصاویر: `python -c "import runpy; runpy.run_path(\'tests/render_step3b.py\', run_name=\'__main__\')"`.']
    (root/cfg['paths']['output']/'step3b_completed_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
