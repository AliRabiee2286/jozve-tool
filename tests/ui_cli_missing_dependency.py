"""Run the real CLI with one module deliberately unavailable, without altering installs."""
import importlib.abc
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
missing = sys.argv[1]


class MissingModule(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] == missing:
            raise ModuleNotFoundError('Simulated missing dependency: ' + missing)
        return None


sys.meta_path.insert(0, MissingModule())
sys.argv = [str(ROOT / 'main.py'), *sys.argv[2:]]
runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
