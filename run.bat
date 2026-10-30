@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
py -3 -c "import pymupdf, openpyxl, yaml, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto use_py
python -c "import pymupdf, openpyxl, yaml, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3 یا وابستگی‌ها آماده نیستند. راهنمای نصب README.md را ببینید.
set result=1
goto finish
:use_py
py -3 main.py %*
set result=%errorlevel%
goto finish
:use_python
python main.py %*
set result=%errorlevel%
:finish
echo گزارش در پوشه خروجی: report.txt
pause
exit /b %result%
