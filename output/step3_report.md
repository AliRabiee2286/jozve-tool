# گزارش مرحلهٔ ۳ — بوردر برداری و حفظ صفحات

وضعیت پذیرش نهایی: **رد / نیازمند تصمیم کاربر**. معیارهای الف تا ه برای چهار فایل قبول‌اند، اما شرط دیداری «محتوا پوشیده نشود» برقرار نیست. هیچ فایل نهایی موفق در output ساخته نشده؛ PDFهای cache فقط خروجی بررسی‌اند.

## روش و کالیبراسیون

صفحات با insert_pdf منتقل شده‌اند؛ هیچ محتوای اصلی به عکس تبدیل نشده است. شش show_pdf_page با clip و overlay=True استفاده می‌شود: دو نوار، هرکدام دو کلاهک با مقیاس یکنواخت و یک بخش سادهٔ میانی با تغییر عرض. rotation و MediaBox و CropBox حفظ می‌شوند. مقصد در جهت مؤثر محاسبه و با derotation_matrix تبدیل می‌شود. برای دور زدن رفتار transformation_matrix در CropBox چرخیده، rotation فقط هنگام درج موقتاً صفر و سپس دقیقاً بازگردانده می‌شود.

| منبع | الگو | نتیجه یکتا |
|---|---|---|
| syllabus | `*Syllabus*.xlsx` | `assets/Comprehensive_Syllabus_19 (1)(1).xlsx` |
| template | `*First_Page_Template*.pdf` | `assets/First_Page_Template (1)(1).pdf` |
| border | `*Sarbarg*.pdf` | `assets/01-Olampiom-Sarbarg-1- (1)(1).pdf` |
| font | `*Aria-Regular*.otf` | `assets/02-Aria-Regular.otf` |

اندازهٔ منبع از اندازه‌گیری مجدد: 595.27600098 × 841.89001465 پوینت، rotation=0، یک صفحه و ۱۴ مسیر برداری. عدد ١ تنها span حذف‌شده است: [30.6089, 810.7967, 34.5316, 827.7780]. حذف با fill=False، images=0 و graphics=0 انجام شد. متن BALATAR.GROUP، ۱۴ مسیر، لوگوها و فلش باقی‌اند. تفاوت رندر اصل و نسخهٔ تمیز بیرون bbox عدد صفر است.

| نوار | y برش | x کلاهک چپ | x کلاهک راست | دلیل |
|---|---|---|---|---|
| هدر | 11 تا 51 | 0 تا 80 | 540 تا عرض منبع | لوگوهای اندازه‌گیری‌شده در x=24.692..75.165 و 545.317..572.858؛ خط هدر با نصف ضخامت stroke تا y=49.982 ادامه دارد. |
| فوتر | 803 تا انتهای صفحه | 0 تا 40 | 460 تا عرض منبع | شکل از y=803.837، نشانی x=469.088..551.360، فلش x=556.605..566.090؛ گوشه‌ها خارج بخش وسط‌اند. |

مختصات و توضیح‌ها در config.yaml هستند. هدر فاصلهٔ مقیاس‌شده از بالا و فوتر اتصال به پایین دارد. مرکز صفحه شفاف و بخش سفید داخل فوتر مات باقی است.

## جدول پذیرش (الف) تا (و)

| فایل | صفحات | الف | ب: اندازه/جهت/rotation | ج: بدون شمارهٔ متنی | د: متن محتوا برابر | ه: نشانی در همه صفحات | و: صفحات مقایسه | بدون پوشش محتوا |
|---|---:|---|---|---|---|---|---|---|
| physics_thermo_10.pdf | 6 | قبول | قبول | قبول | قبول | قبول | 1, 4, 6 | تأیید نشد |
| physics_thermo_8.pdf | 5 | قبول | قبول | قبول | قبول | قبول | 1, 3, 5 | تأیید نشد |
| physics_thermo_9.pdf | 4 | قبول | قبول | قبول | قبول | قبول | 1, 3, 4 | تأیید نشد |
| Savad resane-ma va resane-10.pdf | 9 | قبول | قبول | قبول | قبول | قبول | 1, 5, 9 | تأیید نشد |

«د» با متن دقیق ورودی پس از کنارگذاشتن فقط متن‌های ثبت‌شدهٔ حذف و BALATAR.GROUP بررسی شده است؛ شماره‌ها در ۸٪ انتهایی جهت مؤثر و فقط با fullmatch کل خط حذف می‌شوند. تصاویر با هش بایت‌های تصویر مقایسه شده‌اند. annotationها و مختصاتشان حفظ شده‌اند. حد تشخیص سفید 255 است؛ هر پیکسل غیرسفید هشدار دارد، از جمله خطوط کاغذ. این هشدار به‌تنهایی تشخیص معناییِ نوشته نیست.

## موارد حذف‌شده

| فایل | صفحه | متن حذف‌شده |
|---|---:|---|
| physics_thermo_10.pdf | 1 | New Section 1 Page 1 |
| physics_thermo_10.pdf | 2 | New Section 1 Page 2 |
| physics_thermo_10.pdf | 3 | New Section 1 Page 3 |
| physics_thermo_10.pdf | 4 | New Section 1 Page 4 |
| physics_thermo_10.pdf | 5 | New Section 1 Page 5 |
| physics_thermo_10.pdf | 6 | New Section 1 Page 6 |
| physics_thermo_8.pdf | 1 | New Section 1 Page 1 |
| physics_thermo_8.pdf | 2 | New Section 1 Page 2 |
| physics_thermo_8.pdf | 3 | New Section 1 Page 3 |
| physics_thermo_8.pdf | 4 | New Section 1 Page 4 |
| physics_thermo_8.pdf | 5 | New Section 1 Page 5 |
| physics_thermo_9.pdf | 1 | New Section 1 Page 1 |
| physics_thermo_9.pdf | 2 | New Section 1 Page 2 |
| physics_thermo_9.pdf | 3 | New Section 1 Page 3 |
| physics_thermo_9.pdf | 4 | New Section 1 Page 4 |

مجموع: ۱۵ شماره از ورودی‌های فیزیک؛ سواد رسانه صفر. در بوردر نیز فقط ١ حذف شد. به اعداد داخل جمله و بیرون ناحیهٔ پایین دست زده نشده است.

## هشدارهای پوشش با عدد

مقادیر زیر پس از حذف شمارهٔ متنی‌اند و در ۱۵۰dpi اندازه‌گیری شده‌اند. مقدارهای قبل از حذف، bbox ناحیه، bbox جوهر و همهٔ هشدارها در debug/border_*_qc.json آمده‌اند.

| فایل | صفحه | پیکسل غیرسفید زیر هدر | پیکسل غیرسفید زیر فوتر |
|---|---:|---:|---:|
| physics_thermo_10.pdf | 1 | 7762 | 2 |
| physics_thermo_10.pdf | 2 | 7764 | 2 |
| physics_thermo_10.pdf | 3 | 5216 | 40 |
| physics_thermo_10.pdf | 4 | 1761 | 2 |
| physics_thermo_10.pdf | 5 | 2271 | 2 |
| physics_thermo_10.pdf | 6 | 5216 | 2 |
| physics_thermo_8.pdf | 1 | 7770 | 34 |
| physics_thermo_8.pdf | 2 | 6290 | 2492 |
| physics_thermo_8.pdf | 3 | 5092 | 16 |
| physics_thermo_8.pdf | 4 | 10539 | 2494 |
| physics_thermo_8.pdf | 5 | 7568 | 16 |
| physics_thermo_9.pdf | 1 | 8441 | 70 |
| physics_thermo_9.pdf | 2 | 1899 | 2 |
| physics_thermo_9.pdf | 3 | 5758 | 2 |
| physics_thermo_9.pdf | 4 | 5216 | 2 |
| Savad resane-ma va resane-10.pdf | 1 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 2 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 3 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 4 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 5 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 6 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 7 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 8 | 33267 | 41391 |
| Savad resane-ma va resane-10.pdf | 9 | 33267 | 41391 |

تمام ۲۴ صفحه هشدار دارند؛ این به معنی تشخیص ۲۴ مورد پوشش متن آموزشی نیست. در مشاهدهٔ مستقیم، بالای شکل تلویزیون سواد رسانه با هدر و قسمت پایین آن با فوتر هم‌پوشانی دارد. در فیزیک، بخشی از خطوط کاغذ و در بعضی صفحات نوشته‌های نزدیک لبه با نوارها تداخل دارند. نمونه‌ها محتوا را کوچک‌تر/جابه‌جا نمایش می‌دهند؛ اجرای این کار در این مرحله مجاز نبود.

annotationهای موجود بدون تغییر منتقل شده‌اند؛ نمایشگر PDF آن‌ها را بالای محتوای صفحه و بنابراین بالای بوردر نمایش می‌دهد. برای مثال، در physics_thermo_10 صفحهٔ ۴، annotation سفید بخشی از هدر را می‌پوشاند. هیچ flatten، جابه‌جایی یا حذف annotation انجام نشده است.

## تصاویر و ابهام‌ها

- `debug/border_<نامک>_pN.png`: ۱۲ مقایسهٔ ۱۵۰dpi؛ تولید ما در چپ، نمونه در راست.
- `debug/border_comparison_contact.png`: تماس‌برگ ۱۲ مقایسه.
- `debug/border_overlap_detail.png`: ورودی در چپ و تولید ما در راست، برای نشان‌دادن تعارض پوشش.
- لوگوها و نوشتهٔ فوتر با نسبت اصلی‌اند؛ بخش‌های سادهٔ میانی فقط افقی امتداد یافته‌اند.
- شمارهٔ تصویری: تشخیص خودکار **نامعلوم**؛ تصاویر حذف نشدند. موارد برخورد تصویر با ۸٪ پایین در جدول بعد هستند.
- رفع پوشش نیاز به تغییر یکی از محدودیت‌ها دارد: کوچک‌کردن یکنواخت/جابه‌جایی برداری محتوا برای ایجاد حاشیه، افزایش بوم، یا رد فایل‌های دارای هم‌پوشانی. هیچ‌کدام خودسرانه انجام نشده است.

| فایل | صفحه | تصویرِ وارد ناحیه پایین؛ تشخیص شماره |
|---|---:|---|
| Savad resane-ma va resane-10.pdf | 4 | bbox=[174.5800018310547, 48.239990234375, 724.7999877929688, 504.7200012207031]؛ نامعلوم، حفظ شد |

## سلامت منابع

| فایل | SHA-256 |
|---|---|
| input/physics_thermo_10.pdf | dd541da66a2529549691e28a0bf50e5a49ca29ecff07f2399683f9f1f56e3f14 |
| input/physics_thermo_8.pdf | 9f76b176e4b023d17bdfcdaf51d530062635f425f4173468a390d0b32fef9fd7 |
| input/physics_thermo_9.pdf | b1475820865a5d2c8a6eb7246966274c0e9dca83e67a5c522fd2047f93f7ae1f |
| input/Savad resane-ma va resane-10.pdf | a9c65ed6472efea360a53fd7d3cb338e15257521d3e07e1eb804ec60c56434fc |
| assets/01-Olampiom-Sarbarg-1- (1)(1).pdf | 41497b5e0bda9b89bab146746cd8d3799736295e0f0cf3e9d1538657273cd3a4 |
| assets/02-Aria-Regular.otf | 5fc860fb565bb3b2f5f3d349a6b78bc7f90bcf828adf12e1dc5f625881e8a078 |
| assets/Comprehensive_Syllabus_19 (1)(1).xlsx | 6378a0e61632f164bfec386c39c52f8d71dc3d5cb5c7faa4b0bc8747b8ad344c |
| assets/First_Page_Template (1)(1).pdf | 31605e362644a1caf39e391d224c0542dc8d7e11aabf7f4e55b13dc1d96cab9d |
| samples/LessonNote_hard_physics_thermo_10_v01.pdf | 1cce7f03778f31d2fa6d82c08f80d8d91ca5148f540a80063179f9f72c4879c5 |
| samples/LessonNote_hard_physics_thermo_8_v01.pdf | 86f632260d7ce529cc53db589d40d161e3e4ecaa7eb64a79401765fa09b662b1 |
| samples/LessonNote_hard_physics_thermo_9_v01.pdf | f8bce8c221dc06b111ee2049a41e69169b288c7ab4ea7f4b5474b699062a7cba |
| samples/LessonNote_hard_Savad_resane-ma_va_resane-10_v01.pdf | efc1c21f2d00cc26b49955380613924b4f681f2bc6c4d13e0f327fe1a9eaa516 |

## بازتولید و نتیجهٔ آزمون

فرمان: `python -m pytest --tb=short -q`. آزمون‌های این مرحله تصاویر و JSON و چهار PDF بررسی را دوباره تولید می‌کنند. نتیجهٔ نهایی: **۷۹ قبول، صفر رد، ۱۵۳٫۴۶ ثانیه**؛ ۶۰ تست قبلی و ۱۹ تست مرحلهٔ ۳. در هر ۲۴ صفحه، تغییر پیکسلی بیرون از نوارها و bbox شمارهٔ حذف‌شده صفر است. هش منابع با شواهد مرحلهٔ صفر برابر است. پذیرش دیداری بدون پوشش محتوا همچنان رد است.

تلاش‌های اصلاح: خطای CropBox چرخیده در اجرای نخست تشخیص داده شد و در اولین اصلاح رفع شد؛ هر چهار زاویه ۰/۹۰/۱۸۰/۲۷۰ قبول شدند. برای پوشش محتوا راه‌حل خلاف دستور امتحان نشده است. معیارها سست نشده‌اند.

اصلاح دومِ مستقل: insert_pdf گروه شفافیت /Group را منتقل نمی‌کرد و رندر رنگ محتوای اصلی تفاوت جزئی داشت. با انتقال خود شیء Group و ارجاع‌هایش از طریق graft و حفظ OutputIntents، اولین اصلاح این مشکل آزمون پیکسلیِ بدون تلورانس را قبول کرد. هیچ معیاری تغییر نکرد. API داخلی graft متعلق به PyMuPDF پین‌شدهٔ 1.28.2 است؛ سازگاری با نسخه‌های دیگر نامعلوم است.
