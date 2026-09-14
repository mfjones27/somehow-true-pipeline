from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def repo_root() -> Path:
    pinned = os.environ.get("SOMEHOW_TRUE_ROOT", "").strip()
    if pinned:
        return Path(pinned)
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).resolve().parent
        for candidate in (here, here.parent):
            if (candidate / "daily_pipeline.py").exists() and (candidate / "CONTENT.csv").exists():
                os.environ["SOMEHOW_TRUE_ROOT"] = str(candidate)
                return candidate
        os.environ["SOMEHOW_TRUE_ROOT"] = str(here)
        return here
    return Path(__file__).resolve().parent.parent


ROOT = repo_root()


def load_env() -> None:
    load_dotenv(ROOT / ".env")
