"""Build the final Persian report from measured evidence, never infer a test pass."""
from pathlib import Path
import json
import re
import hashlib
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DEBUG=ROOT/'debug/step5'


def load(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))


def main():
    audit=load('debug/step5/audit.json');benchmark=load('debug/step5/benchmark.json')
    execution=load('output/step5/report.json')['items']
    caps=[piece for item in execution for page in item['pages'] for piece in page['pieces'] if piece['part']!='middle']
    cap_error=max(abs(c['scale_x']-c['scale_y']) for c in caps)
    tests=(ROOT/'cache/step5_final_tests.log').read_text(encoding='utf-8-sig')
    summary=re.search(r'(\d+ passed[^\n]* in [^\n]+)',tests)
    assert summary and not re.search(r'\d+ failed|\d+ error',tests),tests[-2000:]
    final_items=load('output/report.json')['items']
    assert len(final_items)==13 and all(i['status']=='موفق' and all(i['qc']['checks'].values()) for i in final_items)
    assert all(i['qc']['checks']['تعداد شواهد صفحات محتوا'] and i['qc']['checks']['تعداد رندرهای مرجع محتوا'] for i in final_items)
    (DEBUG/'final_cli.json').write_text(json.dumps([
        {'namak':i['namak'],'pages':i['input_pages'],'qc':i['qc']['passed'],
         'evidence_count_check':i['qc']['checks']['تعداد شواهد صفحات محتوا'],
         'render_count_check':i['qc']['checks']['تعداد رندرهای مرجع محتوا']}
        for i in final_items],ensure_ascii=False,indent=2),encoding='utf-8')
    runs={}
    for tag,filename in {'baseline':'step5_baseline.log','qc_red':'step5_qc_red.log',
                         'qc_green':'step5_qc_green.log','cover_isolated':'step5_cover_isolated.log',
                         'first_full_attempt':'step5_final_tests_first.log','final':'step5_final_tests.log'}.items():
        log=(ROOT/'cache'/filename).read_text(encoding='utf-8-sig')
        runs[tag]=next(line for line in reversed(log.splitlines()) if re.search(r'\d+ (?:passed|failed).* in ',line))
    (DEBUG/'test_runs.json').write_text(json.dumps(runs,indent=2),encoding='utf-8')
    offline=load('output/step5_offline/report.json')['items']
    assert len(offline)==1 and offline[0]['qc']['passed']
    pipcheck=(ROOT/'cache/step5_offline_check.log').read_text(encoding='utf-8-sig').strip()
    assert pipcheck=='No broken requirements found.'
    wheel_info=[]
    for path in sorted((ROOT/'cache/step5/wheels').glob('*.whl')):
        with zipfile.ZipFile(path) as z:
            meta=z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))).decode()
        name=re.search(r'^Name: (.+)$',meta,re.M)[1];version=re.search(r'^Version: (.+)$',meta,re.M)[1]
        wheel_info.append({'name':name,'version':version,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (DEBUG/'offline.json').write_text(json.dumps({'pip_check':pipcheck,'cli_passed':True,'wheels':wheel_info,'network_policy':'--no-index --no-cache-dir; HTTP(S)_PROXY=127.0.0.1:9; pip version check disabled'},indent=2),encoding='utf-8')
    lines=['# گزارش نهایی آزمون مستقل مرحلهٔ ۵','',
           'معیارها تغییر نکردند. منابع input، assets و samples فقط خوانده شدند. ردِ مورد نامعتبر، نتیجهٔ درستِ آزمون منفی است؛ به معنی موفقیت پردازش آن PDF نیست.','',
           '## نتیجهٔ اجرای کامل','',f"- مجموعهٔ کامل پس از اصلاح: `{summary[1]}`.",
           f"- اجرای مستقل CLI: {audit['files']} فایل؛ همهٔ QCها: {audit['all_qc']}.",
           f"- هش {len(audit['source_hashes_before'])} منبع پیش و پس برابر: {audit['source_hashes_unchanged']}.",
           f"- {len(caps)} کلاهک: بیشترین اختلاف مقیاس دو محور {cap_error:.3g} (در حد گردکردن محاسبات).",
           '- کنترل صفر تغییر بیرون ناحیه‌های فرست‌پیج، صفر جوهر زیر نوارها و حفظ اندازه/rotation پابرجاست.','',
           '## کشف منابع با الگوهای config','', '| نقش | مسیر کشف‌شده | تعداد |','|---|---|---|']
    for role,path in audit['assets'].items():lines.append(f'| {role} | {path} | ۱ |')
    lines+=['','## مقایسهٔ چهار نمونه','',
            'رندرها در ۸۰ dpi اندازه‌گیری شدند؛ اختلاف با sample شرط صفر ندارد. sampleها متن را تصویری کرده‌اند و در بعضی اندازه‌ها سربرگ کشیده است؛ نسخهٔ ما محتوا را طبق تصمیم مرحلهٔ ۳c یکنواخت کوچک می‌کند. اندازه و rotation خروجی نسبت به ورودی الزاماً برابر می‌ماند.','',
            '| نامک | ورودی / تولید / sample | جهت همه صفحات | اندازه همه صفحات با sample | اختلاف پیکسل فرست‌پیج ٪ | میانگین اختلاف محتوای متناظر ٪ |',
            '|---|---|---|---|---|---|']
    for row in audit['comparisons']:
        pages=row['pages'];vals=[p['different_percent'] for p in pages[1:] if p['different_percent'] is not None]
        lines.append(f"| {row['namak']} | {row['input_pages']} / {row['output_pages']} / {row['sample_pages']} | {all(p['same_orientation'] for p in pages)} | {all(p['same_size'] for p in pages)} | {pages[0]['different_percent']:.3f} | {sum(vals)/len(vals):.3f} |")
    lines+=['','| نامک | صفحهٔ خروجی | اندازهٔ تولید / sample به پوینت | جهت | rotation تولید / sample | اختلاف پیکسل ٪ |',
            '|---|---|---|---|---|---|']
    for row in audit['comparisons']:
        for page in row['pages']:
            a,b=page['ours_size'],page['sample_size']
            direction='افقی' if a[2]-a[0]>a[3]-a[1] else 'عمودی'
            dims=f"{a[2]-a[0]:.3f}×{a[3]-a[1]:.3f} / {b[2]-b[0]:.3f}×{b[3]-b[1]:.3f}"
            diff=page['different_percent']
            lines.append(f"| {row['namak']} | {page['page']} | {dims} | {direction} | {page['ours_rotation']} / {page['sample_rotation']} | {diff:.3f} |")
    lines+=['','ابعاد و اختلاف هر صفحه در debug/step5/audit.json است. تماس‌برگ‌های comparison_01 تا comparison_07 تمام ۲۸ صفحه (۲۴ محتوا و چهار فرست‌پیج) را پوشش می‌دهند؛ تولید چپ و sample راست است. نتیجهٔ بررسی دیداری جداگانه در visual_review.md ثبت می‌شود.','',
            '## آزمون‌های لبه‌ای','', '| حالت | نتیجهٔ پردازش مورد انتظار | مشاهده |','|---|---|---|']
    for path in sorted((ROOT/'output/step5_edges').glob('*/evidence.json')):
        row=json.loads(path.read_text(encoding='utf-8'));status=row['status']
        detail='همهٔ QCها قبول' if status=='موفق' else row['error'].replace('|','/').replace(str(ROOT),'پروژه')
        lines.append(f'| {path.parent.name} | {status} | {detail} |')
    empty=load('output/step5_edges/empty/report.json')['items'][0]
    lines.append(f"| پوشهٔ خالی | خطا | {empty['error']} |")
    lines+=['','نام x در یک workbook آزمایشی ثبت شد؛ فایل «x (1) (1).pdf» به همان x تطبیق کرد. این نامک ساختگی به سیلابس اصلی اضافه نشده است. اجرای دوباره تعداد فایل‌ها را افزایش نداد. آزمون قدیمی CLI نیز بازنویسی تمام ۱۳ خروجی واقعی را بررسی می‌کند.','',
            '| مبحث بلند | تعداد نویسه | فونت نهایی | تعداد خط | تغییر بیرون ناحیه‌ها |','|---|---|---|---|---|']
    for orientation in ('portrait','landscape'):
        record=load(f'output/step5_edges/long_topic_{orientation}.json')['fields']['topic']
        lines.append(f"| {orientation} | {len(record['value'])} | {record['font_size']:.3f} | {record['line_count']} | صفر؛ آزمون مستقیم پیکسل |")
    lines+=['','مبحث چند هزار نویسه‌ای نیز آزمایش شد: TextFitError، بدون بریدن متن.','',
            '## باگ پیدا‌شده و اصلاح','',
            'در qc.py، پیمایش zip روی صفحات و شواهد، در صورت کوتاه بودن شواهد، کنترل صفحات باقی‌مانده را حذف می‌کرد. شواهد اضافه نیز نادیده گرفته می‌شد. دو تست مستقل پیش از اصلاح شکست خوردند: QC به‌اشتباه قبول می‌داد. اکنون تعداد شواهد و تعداد رندرهای مرجع باید دقیقاً برابر تعداد صفحات ورودی باشند؛ در غیر این صورت QC رد می‌شود. چهار تست بازگشتی برای کمبود/اضافه بودن این دو فهرست ثبت شده است. هیچ معیار رندر، اندازه، محتوا یا بوردر تغییر نکرد.','',
            'مشکل دوم در زیرساخت تست بود: fixture فرست‌پیج PDF را در مسیر مشترک debug بازنویسی می‌کرد. اجرای نخستِ مجموعهٔ نهایی با ۱۷۶ قبول و پنج خطای setup در همین فایل مشترک تمام شد (Permission denied). فایل دارای ویژگی read-only نبود؛ علت دقیق سطح سیستم‌عامل، مانند قفل نمایشگر یا ACL، نامعلوم است. اکنون همان PDF ذخیره و بازگشایی‌شده در مسیر اختصاصی tmp_path_factory آزمون قرار می‌گیرد؛ تمام مقایسه‌های رندر و معیارهای پیشین بدون تغییر اجرا می‌شوند. تست شکست‌خورده حذف نشده است.','',
            'خط پایهٔ پیش از تغییر: ۱۵۶ قبول و صفر رد در ۱۲۴۵٫۱۴ ثانیه. دو تست بازتولید شکاف QC پیش از اصلاح رد شدند؛ هفت تست QC پس از اصلاح قبول شدند. اجرای کامل نهایی در ابتدای این گزارش ثبت شده است.','',
            '## زمان پردازش ۵۰ صفحه','',
            f"- زمان دیواری شامل فرست‌پیج، پردازش، ذخیره و QC: **{benchmark['seconds']:.2f} ثانیه**؛ میانگین **{benchmark['seconds_per_page']:.2f} ثانیه برای هر صفحهٔ ورودی**.",
            f"- ورودی: {benchmark['input_pages']} صفحه و {benchmark['input_bytes']} بایت؛ خروجی {benchmark['output_pages']} صفحه؛ QC: {benchmark['qc']}.",
            '- نمونهٔ زمان‌سنجی با ده بار کپی برداری پنج صفحهٔ واقعی thermo_8 ساخته شد؛ یک جزوهٔ مستقل ۵۰ صفحه‌ای واقعی در اختیار نبود. اجرا پس از پایان دو اجرای آزمایشی دیگر شروع شد. سرعت همهٔ جزوه‌های ۵۰ صفحه‌ای از این عدد قابل استنتاج نیست.','',
            '## نصب آفلاین','',
            '- wheelهای نسخه‌های requirements و وابستگی‌های انتقالی ابتدا دریافت شدند؛ خودِ نصب و اجرای بعدی بدون index و با پراکسی نامعتبر انجام شد.',
            '- محیط مجازی تازه: cache/step5/venv؛ system-site-packages غیرفعال؛ نصب با --no-index --no-cache-dir --find-links cache/step5/wheels.',
            f'- pip check: `{pipcheck}`؛ اجرای یک PDF در محیط تازه و QC آن قبول.',
            '- این شبیه‌سازی، قطع فیزیکی شبکه یا آزمون یک رایانهٔ دیگر نیست. wheels و venv وارد commit نمی‌شوند. نسخه و هش wheelها در debug/step5/offline.json است.','',
            '## محدودیت‌های باقی‌مانده','',
            '- این مجموعهٔ محدود، تضمین صحت همهٔ PDFهای آینده نیست؛ بازبینی اولین نمونهٔ هر ساختار جدید لازم است.',
            '- شمارهٔ تصویری و واترمارک OCR نمی‌شوند؛ هشدار تصویر کوچک پایین صفحه به معنی تشخیص قطعی شماره نیست.',
            '- یک عدد مستقل در ناحیهٔ حذف ممکن است محتوای درس باشد؛ برنامه معنای علمی عدد را نمی‌فهمد.',
            '- صفحهٔ مربع، PDF نیازمند رمز، ورودی خراب، نامک مبهم/ناموجود یا مقدار غیرقابل‌جایگذاری ممکن است صریحاً رد شود.',
            '- کالیبراسیون سربرگ و رنگ خطوط کاغذ مربوط به منابع فعلی است؛ منبع تازه نیاز به آزمون دارد.',
            '- تبدیل واقعی Word/PowerPoint با LibreOffice، امضای دیجیتال، فرم پیچیده و همهٔ نمایه‌های رنگ در این مرحله تأیید نشده‌اند؛ نامعلوم.',
            '- tests/test_cli.py هنوز برای مجموعهٔ مرجع ۱۳ ورودی تنظیم شده است؛ افزودن ورودی به input ممکن است آن آزمون شمارشی را رد کند، حتی اگر CLI فایل جدید را درست پردازش کند.',
            '- مقایسهٔ sample، برابری پیکسلی محتوا را اثبات نمی‌کند؛ کنترل‌های حفظ محتوای مستقل مجموعهٔ تست‌ها و QC مکمل آن هستند.','',
            '## بازتولید','',
            '```text','python -m pytest -q --tb=short','python tests/audit_step5.py','python tests/audit_step5.py --benchmark','python tests/report_step5.py','```','',
            'گیت: پیام مرحله step 5 است؛ هش و نتیجهٔ push در پاسخ نهایی اعلام می‌شود.']
    (ROOT/'output/final_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(summary[1])


if __name__=='__main__':main()
