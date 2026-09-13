"""Use this sandbox's existing system pytest without installing/downloading anything.

Append, do not prepend: application dependencies must remain those of local Python.
This convenience runner is not needed in a normal virtual environment.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append("/usr/lib/python3/dist-packages")

import pytest

raise SystemExit(pytest.main([str(ROOT / "tests"), *sys.argv[1:]]))

