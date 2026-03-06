"""Pytest conftest: ensure project root is on path so eval_engine is importable."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
