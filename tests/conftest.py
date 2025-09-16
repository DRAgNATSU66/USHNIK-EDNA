# tests/conftest.py
import sys
from pathlib import Path

# repo root is two levels up from this file if tests/ is at repo/tests/
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
