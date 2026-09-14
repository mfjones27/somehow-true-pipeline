"""Windows exe entry. Starts the studio with the same taskbar identity as the pin."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import traceback
import urllib.request
from pathlib import Path

APP_ID = "SomehowTrue.Studio"
WINDOW_TITLE = "Somehow True"
HEALTH = "http://127.0.0.1:8765/health"


def _message(title: str, text: str, error: bool = True) -> None:
    if sys.platform != "win32":
        print(text)
        return
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)


def _set_app_id() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def _focus_existing() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    ctypes.windll.user32.ShowWindow(hwnd, 9)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    return True


def repo_root() -> Path:
    here = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    for candidate in (here, here.parent):
        if (candidate / "desktop.py").exists() and (candidate / "daily_pipeline.py").exists():
            return candidate
    raise FileNotFoundError(
        "This shortcut is not in the pipeline folder.\n"
        f"Looked in:\n{here}\n{here.parent}\n\n"
        "Pin Somehow True from the somehow-true-pipeline folder."
    )


def pythonw_bin(root: Path) -> str:
    dirs = [
        root / ".venv" / "Scripts",
        Path(sys.executable).resolve().parent,
        Path(r"C:\Python314"),
        Path(r"C:\Python313"),
        Path(r"C:\Python312"),
        Path(r"C:\Users\Mauri\AppData\Local\Programs\Python\Python314"),
        Path(r"C:\Users\Mauri\AppData\Local\Programs\Python\Python313"),
    ]
    which = shutil.which("pythonw")
    if which:
        dirs.append(Path(which).resolve().parent)
    for folder in dirs:
        pythonw = folder / "pythonw.exe"
        if pythonw.exists() and pythonw.name.lower() != "somehowtrue.exe":
            return str(pythonw)
    for folder in dirs:
        python = folder / "python.exe"
        if python.exists() and python.name.lower() not in {"somehowtrue.exe", "somehow true.exe"}:
            return str(python)
    raise FileNotFoundError("Python was not found. Install Python 3 and retry.")


def _studio_alive() -> bool:
    try:
        with urllib.request.urlopen(HEALTH, timeout=0.6) as resp:
            return resp.status == 200
    except Exception:
        return False


def main() -> int:
    try:
        _set_app_id()
        if _studio_alive() and _focus_existing():
            return 0
        root = repo_root()
        os.chdir(root)
        py = pythonw_bin(root)
        log_path = root / "pipeline_output" / "studio-launch.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["SOMEHOW_TRUE_ROOT"] = str(root)
        env["PYTHONUNBUFFERED"] = "1"
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"root={root}\npython={py}\nexe={sys.executable}\n")
        creation = 0
        if sys.platform == "win32":
            creation = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            [py, "-u", str(root / "desktop.py")],
            cwd=str(root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
            close_fds=True,
            start_new_session=True,
        )
        return 0
    except Exception:
        _message("Somehow True", traceback.format_exc()[-1500:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
