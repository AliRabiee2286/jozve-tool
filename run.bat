@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" goto probe_312
call ".venv\Scripts\python.exe" -c "import pymupdf, openpyxl, yaml, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto use_venv
:probe_312
call py -3.12 -c "import pymupdf, openpyxl, yaml, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto use_312
call py -3 -c "import pymupdf, openpyxl, yaml, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto use_py
call python -c "import pymupdf, openpyxl, yaml, numpy, PIL" >nul 2>&1
if not errorlevel 1 goto use_python
echo Python 3 or required packages are unavailable. See README.md.
set result=1
goto finish
:use_venv
call ".venv\Scripts\python.exe" main.py %*
set result=%errorlevel%
goto finish
:use_312
call py -3.12 main.py %*
set result=%errorlevel%
goto finish
:use_py
call py -3 main.py %*
set result=%errorlevel%
goto finish
:use_python
call python main.py %*
set result=%errorlevel%
:finish
echo Report: output\report.txt
pause
exit /b %result%
