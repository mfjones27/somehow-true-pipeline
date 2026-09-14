"""Somehow True desktop window. Starts the local API and opens the React UI."""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

os.environ["DESKTOP_MODE"] = "true"
os.environ["PIPELINE_ENABLED"] = "true"
os.environ.setdefault("SOMEHOW_TRUE_PORT", "8765")

if getattr(sys, "frozen", False):
    os.environ.setdefault("SOMEHOW_TRUE_ROOT", str(Path(sys.executable).resolve().parent))

from providers.env import ROOT, load_env

load_env()

PORT = int(os.environ.get("SOMEHOW_TRUE_PORT", "8765"))
HOST = "127.0.0.1"
URL = f"http://{HOST}:{PORT}"


def _wait_for_server(timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Studio did not start on {URL}")


def _run_server() -> None:
    import uvicorn
    from app import app

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main() -> int:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SomehowTrue.Studio")

    try:
        threading.Thread(target=_run_server, daemon=True).start()
        _wait_for_server()
        import webview
        icon = ROOT / "ui" / "icon.ico"
        webview.create_window(
            "Somehow True",
            URL,
            width=1320,
            height=880,
            min_size=(900, 640),
        )
        webview.start(icon=str(icon) if icon.exists() else None)
        return 0
    except Exception as exc:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Somehow True", 0x10)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
