"""Run pytest with a fresh, time-stamped temporary directory."""
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid


ROOT=Path(__file__).resolve().parents[1]
TESTS=ROOT/'tests'


def clean_old_temp_dirs():
    for path in TESTS.glob('.pytest_tmp*'):
        try:
            if path.is_dir():
                shutil.rmtree(path)
        except OSError:
            pass


def main():
    clean_old_temp_dirs()
    stamp=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    basetemp=TESTS/f'.pytest_tmp_{stamp}'
    command=[sys.executable,'-m','pytest',f'--basetemp={basetemp}',*sys.argv[1:]]
    return subprocess.call(command,cwd=ROOT)


if __name__=='__main__':
    raise SystemExit(main())
