"""Render final saved outputs and write the Persian stage report after acceptance."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
import pymupdf as fitz
from syllabus import load_config,discover_assets
from pages import raster


def main():
    root=Path(__file__).resolve().parents[1];cfg=load_config();assets=discover_assets(cfg,root)
    output=root/cfg['paths']['output'];debug=root/cfg['paths']['debug']
    report=json.loads((output/'report.json').read_text(encoding='utf-8'))
    lines=['# گزارش مرحلهٔ ۴ — اجرای یکپارچه و QC','',
           'main.py از همان pages.process_pages استفاده می‌کند: کپی برداری، bake، حذف شماره، کوچک‌سازی یکنواخت و بوردر. فایل موقت تنها پس از بازکردن مجدد و قبولی همهٔ کنترل‌ها با os.replace منتشر می‌شود. خطای یک ورودی مانع بقیه نیست.','',
           '| ورودی | نامک کانونی | رشته | صفحات ورودی / خروجی | نتیجه | هشدار تصویری |',
           '|---|---|---|---:|---|---:|']
    for item in report['items']:
        assert item['status']=='موفق' and item['qc']['passed']
        lines.append(f'| {", ".join(item["files"])} | {item["namak"]} | {item["sheet"]} | {item["input_pages"]} / {item["output_pages"]} | قبول | {len(item["warnings"])} |')
        with fitz.open(output/item['output']) as doc:
            selected=sorted({0,1,len(doc)//2,len(doc)-1});thumbs=[]
            for n in selected:
                im=Image.fromarray(raster(doc[n],100));im.thumbnail((800,900));thumbs.append((n,im))
            canvas=Image.new('RGB',(1600,1900),'white')
            draw=ImageDraw.Draw(canvas)
            for j,(n,im) in enumerate(thumbs):
                x=j%2*800;y=j//2*950;canvas.paste(im,(x,y+25));draw.text((x+5,y+5),f'{item["namak"]}: output page {n+1}',fill='black')
            canvas.save(debug/('step4_'+Path(item['output']).stem+'.png'))
    lines+=['','## کنترل‌ها','',
            '۴۲ صفحهٔ محتوا در شش ورودی و ۴۸ صفحهٔ خروجی با فرست‌پیج. هر ۸۴ ناحیهٔ هدر/فوتر جوهر معنادار صفر دارد. QC روی PDF ذخیره‌شده، پس از کنارگذاشتن streamهای ثبت‌شدهٔ بوردر در یک کپی حافظه‌ای، دوباره جوهر را می‌شمارد؛ دادهٔ گزارش تولید به‌تنهایی معیار قبولی نیست. شمارش streamها نیز کنترل می‌شود. آزمون منفی جوهر پنهان زیر هدر رد می‌شود.',
            '', 'تعداد صفحات، هندسه و rotation، متن پس از حذف شماره، BALATAR.GROUP، نبود شمارهٔ متنی، جاسازی بایت‌های فونت Aria، نام فایل و رندر پس از مونتاژ کنترل می‌شوند. برای فرست‌پیج استخراج متن استفاده نمی‌شود: تغییر نسبت به تمپلیت فقط در چهار ناحیه، تغییر در هر چهار ناحیه و برابری با مرجع نوشتن لازم است. مقدارهای گزارش نوشتن نیز با چهار مقدار دقیق سیلابس مقایسه می‌شوند.',
            '', 'در فایل اقتصاد GO، redaction برای تصاویر تکرارشونده نام‌های مستعار تازه ساخت: در صفحهٔ ۳، ۲۴ مدخل تصویر به ۳۸ نام مستعار تبدیل شد، بدون حذف تصویر. QC هم هش بایت‌های تصاویر یکتا و هم digest، ابعاد و تعداد تمام کاربردهای تصاویر را مقایسه می‌کند. آزمون مستقل حذف/افزودن کاربرد تکراری را رد می‌کند؛ معیار حفظ تصویر با شمارش نام مستعار اشتباه گرفته نمی‌شود.',
            '', 'آستانهٔ هشدار تصویر کوچک در config برابر ۰٫۳۰ است؛ تصویر تمام‌صفحه هشدار شماره ندارد. سه هشدار باقی‌ماندهٔ GO برای تصاویر کوچک پایین صفحه‌اند و حذف نشده‌اند. پس‌زمینهٔ تمام‌رنگ همراه محتوا کوچک می‌شود و حاشیهٔ سفید دارد.',
            '', 'نام خروجی GO از نامک «ECONO GO P 7» ساخته می‌شود: LessonNote_hard_ECONO_GO_P_7_v01.pdf؛ نام قدیمی sample با دو زیرخط مبنای نام‌گذاری نیست.',
            '', '## پایداری ویندوز و خطاها','',
            'هر کار cache موقت مستقل برای بوردر و تبدیل Office دارد؛ قفل بوردر مشترک در اجرای هم‌زمان رفع شد. CLI و run.bat هر دو UTF-8 را فعال می‌کنند. گزارش فارسی BOM دارد. run.bat ابتدا py -3 و سپس python را امتحان می‌کند و pause دارد. خروجی قدیمی در صورت رد QC حفظ و در گزارش صریحاً قدیمی اعلام می‌شود.',
            '', 'LibreOffice خودکار نصب نمی‌شود. مسیر PATH و محل‌های رایج بررسی می‌شوند؛ آزمون نبود آن پیام «LibreOffice نصب نیست» را کنترل می‌کند. تبدیل واقعی Word/PowerPoint با LibreOffice روی این سیستم تأیید نشده و نامعلوم است. fallback واقعی از py -3 (پایتون ۳٫۱۴ فاقد وابستگی‌ها) به python (پایتون ۳٫۱۲ آماده) در آزمون run.bat قبول شد.',
            '', '## منابع و بازبینی','']
    lines += [f'- {role}: `{path.relative_to(root).as_posix()}`' for role,path in assets.items()]
    lines+=['', 'تصاویر `debug/step4_LessonNote_hard_*.png` فرست‌پیج، صفحهٔ اول محتوا، میانی و آخر هر خروجی را نشان می‌دهند. گزارش هر بررسی در output/report.txt و نسخهٔ ساختاری در output/report.json؛ لاگ در output/log.txt است. نتیجهٔ نهایی تست‌ها و commit/push در پاسخ پایان مرحله ثبت می‌شود.']
    (output/'step4_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__': main()
