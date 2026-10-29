# گزارش توقف مرحلهٔ ۳b: آزمون bake

طبق دستور «اگر bake جواب نداد، قبل از هر راه دیگری گزارش بده و بپرس»، هیچ روش جایگزین یا اصلاح خودکار روی bake اجرا نشد. هیچ PDF تولیدی با bake ذخیره نشده و pages.py، border.py و config.yaml تغییر نکرده‌اند.

## نتیجهٔ قابل بازتولید

فرمان: `python -m pytest tests/test_bake.py -q --tb=short`؛ ۲۰ قبول، ۴ رد، ۱۷٫۲۳ ثانیه. آزمون مستقل سلامت ۱۲ فایل منبع نیز قبول شد. نسخه PyMuPDF: 1.28.2؛ رندر RGB در ۱۵۰dpi، بدون بوردر، مقایسهٔ دقیق همهٔ کانال‌ها. صفحات با insert_pdf و حفظ Group در حافظه کپی شدند و تنها Document.bake(annots=True, widgets=False) روی نسخهٔ آزمایشی اجرا شد.

| فایل | صفحه | annotation قبل/بعد | widget قبل/بعد | تعداد پیکسل متفاوت | بیشترین اختلاف کانال از ۲۵۵ |
|---|---:|---|---|---:|---:|
| physics_thermo_10.pdf | 1 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_10.pdf | 2 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_10.pdf | 3 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_10.pdf | 4 | 3/0 | 0/0 | 1746 | 1 |
| physics_thermo_10.pdf | 5 | 2/0 | 0/0 | 1450 | 1 |
| physics_thermo_10.pdf | 6 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_8.pdf | 1 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_8.pdf | 2 | 2/0 | 0/0 | 624 | 1 |
| physics_thermo_8.pdf | 3 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_8.pdf | 4 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_8.pdf | 5 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_9.pdf | 1 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_9.pdf | 2 | 6/0 | 0/0 | 1422 | 1 |
| physics_thermo_9.pdf | 3 | 0/0 | 0/0 | 0 | 0 |
| physics_thermo_9.pdf | 4 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 1 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 2 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 3 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 4 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 5 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 6 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 7 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 8 | 0/0 | 0/0 | 0 | 0 |
| Savad resane-ma va resane-10.pdf | 9 | 0/0 | 0/0 | 0 | 0 |

چهار صفحهٔ دارای annotation در مجموع ۵۲۴۲ پیکسل متفاوت دارند. اختلاف هر کانال حداکثر ۱ است؛ با وجود کوچک‌بودن اختلاف، شرط «صفر» رد است. علت دقیق اختلاف **نامعلوم** است؛ به آنتی‌الیاس نسبت داده نشده و تلورانس افزایش نیافته است. هر ۲۴ صفحه فاقد widget هستند؛ رفتار روی فایل دارای widget در این مرحله **آزمایش نشده** است.

## شاهد تصویری

در تصاویر زیر، قبل در چپ، بعد از bake در وسط و نقشهٔ اختلاف دقیق با رنگ قرمز در راست است. bbox و تعدادها در debug/bake_step3b.json ثبت شده‌اند.
- `debug/bake_physics_thermo_10_p4.png`
- `debug/bake_physics_thermo_10_p5.png`
- `debug/bake_physics_thermo_8_p2.png`
- `debug/bake_physics_thermo_9_p2.png`

## کشف منابع

هر چهار الگوی config دقیقاً یک نتیجه داشتند:
- syllabus: `assets/Comprehensive_Syllabus_19 (1)(1).xlsx`
- template: `assets/First_Page_Template (1)(1).pdf`
- border: `assets/01-Olampiom-Sarbarg-1- (1)(1).pdf`
- font: `assets/02-Aria-Regular.otf`

## کارهای باقی‌مانده و تصمیم لازم

- در خوانش اولیهٔ مسیرهای برداری، رنگ خطوط افقی تکرارشوندهٔ فیزیک RGB=(0.792, 0.922, 0.992)، ضخامت 0.48 پوینت بود. این فقط مشاهده است؛ هنوز آستانهٔ جوهر معنادار کالیبره یا در config ثبت نشده است.
- معیار پوشش فعلی تغییر نکرده؛ جدول جدید جوهر معنادار و cropهای مربوط به آن هنوز ساخته نشده‌اند.
- تصاویر کامل ۲۴ صفحه و تماس‌برگ‌های جدید هنوز ساخته نشده‌اند؛ تصاویر مرحلهٔ ۳ همان نسخهٔ قبلی‌اند.
- هیچ کوچک‌سازی، جابه‌جایی، تغییر اندازه یا رندر محتوای PDF به تصویر انجام نشده است.
- برای ادامه: آیا بررسی راهکار برداری دیگری با حفظ شرط صفر اختلاف پیکسلی مجاز است؟

مرحله تمام نیست. تست‌های الف تا ه و منطق تولید مرحلهٔ ۳ دست‌نخورده‌اند؛ آزمون جدید bake عمداً شرط دقیق درخواست‌شده را حفظ می‌کند و چهار شکست واقعی را پنهان نمی‌کند. به‌دلیل تست ردشده، commit طبق AGENTS.md باید پیشوند WIP داشته باشد.
