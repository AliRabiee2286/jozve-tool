"""Stage 3: launcher ordering and a real one-file Windows run."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import pytest


ROOT=Path(__file__).resolve().parents[1]
LAUNCHER=ROOT/'run.bat'
pytestmark=pytest.mark.slow


def run_launcher(folder, *args, input_text='\r\n', env=None):
    return subprocess.run(['cmd','/c',str(folder/'run.bat'),*map(str,args)],
                          cwd=folder,input=input_text,capture_output=True,text=True,
                          encoding='utf-8',errors='replace',env=env,timeout=180)


@pytest.mark.skipif(sys.platform!='win32',reason='Windows batch launcher')
def test_launcher_order_and_fallback_simulation(tmp_path):
    launcher=tmp_path/'run.bat';shutil.copyfile(LAUNCHER,launcher)
    (tmp_path/'main.py').write_text('',encoding='utf-8')
    fake_py=tmp_path/'py.cmd'
    fake_py.write_text(
        '@echo off\n'
        '>>"%~dp0calls.txt" echo py %*\n'
        'if "%1"=="-3.12" if "%2"=="-c" exit /b 1\n'
        'if "%1"=="-3" if "%2"=="-c" exit /b 0\n'
        'if "%2"=="main.py" >>"%~dp0selected.txt" echo py %1\n'
        'exit /b 0\n',encoding='ascii')
    fake_python=tmp_path/'python.cmd'
    fake_python.write_text(
        '@echo off\n'
        '>>"%~dp0calls.txt" echo python %*\n'
        'exit /b 0\n',encoding='ascii')
    env=os.environ.copy();env['PATH']=str(tmp_path)+os.pathsep+env.get('PATH','')
    result=run_launcher(tmp_path,'--logical-test',env=env)
    assert result.returncode==0,result.stdout+result.stderr
    calls=(tmp_path/'calls.txt').read_text(encoding='utf-8').splitlines()
    assert calls[0].startswith('py -3.12 -c ')
    assert any(line.startswith('py -3 -c ') for line in calls)
    assert all(not line.startswith('python ') for line in calls)
    assert (tmp_path/'selected.txt').read_text(encoding='utf-8').strip()=='py -3'
    assert 'Report: output\\report.html' in result.stdout


@pytest.mark.skipif(sys.platform!='win32',reason='Windows batch launcher')
def test_launcher_real_one_input(tmp_path):
    source=tmp_path/'physics_thermo_8.pdf'
    shutil.copyfile(ROOT/'input/physics_thermo_8.pdf',source)
    output=ROOT/'output/step3_launcher'
    result=subprocess.run(['cmd','/c',str(LAUNCHER),'--input',str(source),
                           '--output',str(output)],cwd=ROOT,input='\r\n',
                          capture_output=True,text=True,encoding='utf-8',
                          errors='replace',timeout=300)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'Summary: OK=1 REVIEW=0 BLOCKED=0' in result.stdout
    assert list(output.glob('LessonNote_*.pdf'))
    assert 'Report: output\\report.html' in result.stdout
